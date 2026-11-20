# DensaMed AI forecast demo (A5)

This is an academic Odoo 17 addon. Sales history is **simulated**. It does not
create fake `densamed.sale` receipts or claim to forecast actual business demand.

## Use

Install `densamed_ai`, open **Sales → AI Forecast Demo**, create a run, select a
branch warehouse, and click **Train and Forecast**. The button syncs the 20
seeded medicines through the existing bridge if needed. It then:

1. Writes a deterministic 120-day `salesdaily.csv` for those medicine codes to
   Odoo's data directory (`ai_demo/`).
2. Computes seven-day averages and trends.
3. Trains a Random Forest on lag, rolling mean, product, and calendar features.
   The last 14 historical days are held out for MAE/RMSE comparison with a
   seven-day mean baseline. The model is then refit on all 120 days and saved as
   `ai_demo/forecast_model.joblib`.
4. Predicts seven days of demand per medicine and compares it with available
   Odoo stock, pending incoming moves, and `product.template.min_stock`.

Replenishment = `max(0, ceil(predicted 7-day units + safety stock - available - incoming))`.
The UI is a report; it does not automatically create purchase orders.

The same generated CSV and saved model are overwritten by each demo run. Forecast
results and evaluation metrics remain on the Odoo run record. The model is trained
and used in memory in the same action; the saved artifact supports inspection and
reproduction, rather than serving as an unvalidated production model.
