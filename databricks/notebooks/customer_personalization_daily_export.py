# Databricks notebook source
# MAGIC %md
# MAGIC # Customer personalization - daily export for the Couchbase Delivery app
# MAGIC
# MAGIC Runs every morning (see `../jobs/customer_personalization_daily_export.job.json`, 04:30 America/New_York).
# MAGIC
# MAGIC 1. Join every active customer with Customer 360 (membership, wallet, household, home hub, delivery
# MAGIC    defaults, preferences, engagement), the last orders and per-SKU replenishment.
# MAGIC 2. Score every customer with the registered next-basket model (`delivery_next_basket`, alias `champion`):
# MAGIC    category affinities, a smart cart with a confidence per line, days-to-runout, recommended items with a
# MAGIC    reason, churn risk. Join the competitor price watch from the pricing pipeline.
# MAGIC 3. Write the Delta table `delivery_prod.customer360.customer_personalization_daily`.
# MAGIC 4. Export the same rows as JSON Lines to a Unity Catalog volume partitioned by `dt=`,
# MAGIC    with `_SUCCESS` and `_manifest.json` - the drop the demo backend's loader picks up and
# MAGIC    publishes to Couchbase (operational + Couchbase Lite sync) and the AOM Knowledge Base.
# MAGIC
# MAGIC **This is the only Databricks compute the app ever uses.** Every profile read, recommendation,
# MAGIC price quote and assistant answer during the day is served from Couchbase (or from Couchbase Lite on
# MAGIC the customer's phone), not from a SQL warehouse or a Model Serving endpoint. One scheduled job, once a day.
# MAGIC
# MAGIC In this repo the same output is produced locally by `databricks/generate_mock_dump.py`
# MAGIC (mock data, identical schema), so the demo runs without a Databricks workspace.

# COMMAND ----------

dbutils.widgets.text("catalog", "delivery_prod")
dbutils.widgets.text("schema", "customer360")
dbutils.widgets.text("export_volume", "/Volumes/delivery_prod/customer360/exports/customer_personalization_daily")
dbutils.widgets.text("history_orders", "8")
dbutils.widgets.text("num_files", "4")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EXPORT = dbutils.widgets.get("export_volume")
HISTORY = int(dbutils.widgets.get("history_orders"))
NUM_FILES = int(dbutils.widgets.get("num_files"))
SCHEMA_VERSION = "customer_personalization_v1"

import datetime as dt
import json

from pyspark.sql import functions as F
from pyspark.sql import Window

export_date = dt.date.today().isoformat()
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------
# MAGIC %md ## 1. Active customers + Customer 360

# COMMAND ----------

customers = spark.table("customers_current").where(F.col("status") == "Active")
hubs = spark.table("hubs").select(F.col("hub_id").alias("home_hub_id"), F.col("name").alias("home_hub_name"),
                                      F.col("city").alias("home_hub_city"), "region_id", "region_name", "fulfillment_center")
household = spark.table("household_profile")                # type, type_name, size, pets
membership = spark.table("rewards_membership")              # tier, tier_name, discount_pct, member_since, renewal_date
wallet = spark.table("wallet_balances")                     # store_credit_usd, points, payment_method (masked)
delivery = spark.table("customer_delivery_profile")          # default_option, delivery_notes, preferred_window (model-predicted)
preferences = spark.table("customer_preferences")            # favorite_categories, avoid_categories, allow_substitutions
engagement = spark.table("app_engagement_30d")              # last_app_open, sessions_30d, connectivity_note, push_opt_in
orders = (
    spark.table("orders").join(spark.table("order_lines").groupBy("order_id").agg(
        F.collect_list(F.struct("sku", "name", "qty", "unit_price", "line_total")).alias("lines"),
        F.count("*").alias("line_count")), "order_id")
    .withColumn("rn", F.row_number().over(Window.partitionBy("customer_id").orderBy(F.desc("order_date"))))
    .where(f"rn <= {HISTORY}")
    .groupBy("customer_id")
    .agg(F.collect_list(F.struct(F.col("order_id"), F.col("order_date").alias("date"), "status", "channel", "delivery_option",
                                 "line_count", "lines", "subtotal_usd", "total_usd", "backordered")).alias("order_history"))
)
replenishment = spark.table("sku_replenishment_90d")        # map<sku, struct<avg_monthly_qty, last_ordered, last_qty>>
spend = spark.table("customer_spend_12m")                    # last_12mo_usd, ytd_usd, avg_order_usd, orders_last_12mo, category_mix
subscriptions = spark.table("subscriptions_active")         # array<struct<sku,name,qty,unit_price,cadence_weeks,next_date>>
price_watch = (
    spark.table(f"{CATALOG}.pricing.competitor_price_watch")   # one row per customer + watched sku where a competitor is lower
    .groupBy("customer_id")
    .agg(F.collect_list(F.struct("sku", "competitor", "competitor_price_usd", "seen_on")).alias("price_watch"))
)

base = (
    customers.join(hubs, "home_hub_id").join(household, "customer_id", "left").join(membership, "customer_id")
    .join(wallet, "customer_id").join(delivery, "customer_id").join(preferences, "customer_id", "left")
    .join(engagement, "customer_id", "left").join(orders, "customer_id", "left")
    .join(replenishment, "customer_id", "left").join(spend, "customer_id", "left").join(subscriptions, "customer_id", "left")
    .join(price_watch, "customer_id", "left")
)

# COMMAND ----------
# MAGIC %md ## 2. Score with the next-basket model

# COMMAND ----------

import mlflow

mlflow.set_registry_uri("databricks-uc")
model_uri = f"models:/{CATALOG}.ml.delivery_next_basket@champion"
score_udf = mlflow.pyfunc.spark_udf(spark, model_uri, result_type="string")  # returns JSON of ml_scores
model_version = mlflow.MlflowClient().get_model_version_by_alias(f"{CATALOG}.ml.delivery_next_basket", "champion").version

# No direct identifiers go to the model.
feature_cols = [c for c in base.columns if c not in ("first_name", "last_name", "email", "street", "member_number", "payment_method")]
scored = base.withColumn("ml_scores_json", score_udf(F.struct(*feature_cols)))

# COMMAND ----------
# MAGIC %md ## 3. Shape to the export schema and write Delta

# COMMAND ----------

ml_schema = ("struct<model_version:string,scored_at:string,pantry_affinity:double,household_affinity:double,"
             "personal_affinity:double,baby_affinity:double,pets_affinity:double,kitchen_affinity:double,"
             "electronics_affinity:double,toys_affinity:double,outdoor_affinity:double,"
             "churn_risk:double,predicted_basket_usd:double,days_to_runout:map<string,int>,"
             "replenish_lines:array<struct<sku:string,qty:int,confidence:double,reason:string>>,"
             "recommended:array<struct<sku:string,confidence:double,reason:string>>,segment:string,next_best_offer:string>")

ml = F.from_json("ml_scores_json", ml_schema)
out = scored.select(
    F.lit(export_date).alias("export_date"),
    F.lit(SCHEMA_VERSION).alias("schema_version"),
    "customer_id", "member_number", "first_name", "last_name", "email",
    F.struct("street", "city", "state", "zip").alias("address"),
    "region_id", "region_name",
    F.struct(F.col("home_hub_id").alias("hub_id"), F.col("home_hub_name").alias("name"),
             F.col("home_hub_city").alias("city")).alias("home_hub"),
    F.struct(F.col("household_type").alias("type"), F.col("household_type_name").alias("type_name"),
             F.col("household_size").alias("size"), "pets").alias("household"),
    F.struct("tier", "tier_name", "discount_pct", "member_since", "renewal_date").alias("membership"),
    F.struct("store_credit_usd", "points", "payment_method").alias("wallet"),
    F.struct("default_option", F.col("delivery_notes").alias("notes"), "preferred_window", "fulfillment_center").alias("delivery"),
    F.struct("favorite_categories", "avoid_categories", "allow_substitutions").alias("preferences"),
    F.struct("last_app_open", "sessions_30d", "connectivity_note", "push_opt_in").alias("engagement"),
    "order_history", "replenishment",
    F.struct("last_12mo_usd", "ytd_usd", "avg_order_usd", "orders_last_12mo", "category_mix").alias("spend"),
    "subscriptions",
    ml.withField("price_watch", F.coalesce("price_watch", F.array())).alias("ml_scores"),
    F.struct(F.lit(f"{CATALOG}.{SCHEMA}.customer_personalization_daily").alias("source_table"),
             F.lit("customer_personalization_daily_export").alias("pipeline"),
             F.lit(spark.conf.get("spark.databricks.clusterUsageTags.sparkVersion", "")).alias("dbr_version"))
    .alias("_ingest"),
)

(out.write.format("delta").mode("overwrite").option("replaceWhere", f"export_date = '{export_date}'")
    .partitionBy("export_date").saveAsTable("customer_personalization_daily"))

# COMMAND ----------
# MAGIC %md ## 4. Export JSON Lines for the app (dt= partition + _SUCCESS + _manifest.json)

# COMMAND ----------

path = f"{EXPORT}/dt={export_date}"
daily = spark.table("customer_personalization_daily").where(F.col("export_date") == export_date)
daily.repartition(NUM_FILES).write.mode("overwrite").json(path)   # Spark writes part-*.json + _SUCCESS

files = [f for f in dbutils.fs.ls(path) if f.name.startswith("part-")]
manifest = {
    "table": f"{CATALOG}.{SCHEMA}.customer_personalization_daily",
    "export_date": export_date, "schema_version": SCHEMA_VERSION,
    "model_version": f"delivery-next-basket-v{model_version}", "format": "jsonl",
    "rows": daily.count(), "hubs": daily.select("home_hub.hub_id").distinct().count(),
    "bytes": sum(f.size for f in files), "files": [{"file": f.name, "bytes": f.size} for f in files],
}
dbutils.fs.put(f"{path}/_manifest.json", json.dumps(manifest, indent=2), overwrite=True)
print(json.dumps(manifest, indent=2))

# COMMAND ----------
# MAGIC %md
# MAGIC ## Delivery to the demo backend
# MAGIC The backend watches `DUMP_DIR` for a newer `dt=*/_SUCCESS`. Point it at wherever this volume lands:
# MAGIC * copy it down: `databricks fs cp -r dbfs:/Volumes/.../dt=<date> ./data/databricks-dump/dt=<date>`
# MAGIC * or mount the cloud storage location behind the volume into the backend container at `/data/databricks-dump`.
# MAGIC
# MAGIC After this job finishes, Databricks is done for the day: the warehouse can auto-stop.
