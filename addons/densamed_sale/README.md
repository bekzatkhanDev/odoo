# densamed_sale — Pharmacy Sales (Сату)

Odoo 17 Community addon for the DensaMed pharmacy chain. Depends on
`densamed_bridge` (branch groups, `requires_prescription`, synced lots) and
`product_expiry` (`stock.lot.expiration_date`).

## What it does
- **Sale (`densamed.sale`)**: one receipt per branch (= `res.company`) and warehouse;
  states `draft → completed → returned` or `cancelled` (same as `densamed.sales`).
- **FEFO**: lines without a batch get the earliest-expiring non-expired batch when
  the sale is completed; a line is split across batches if one is not enough.
  Expired batches are never sold.
- **Prescription**: if any medicine has `requires_prescription`, a prescription
  number is mandatory.
- **Payments**: cash / card / bank transfer / other. No payment rows → one full
  payment is created from the chosen method; split payments must sum to the total.
- **Stock**: completing validates a standard outgoing `stock.picking`
  (lot-level move lines); returning validates the reverse incoming picking and
  marks payments `refunded`. `stock.quant` is never written directly.
- **Security**: groups *Cashier* / *Sales Manager*, multi-company record rules,
  read access for the bridge HQ group.
- **Analysis**: pivot/graph of completed sale lines (Sales Manager).

## Install
```
docker compose exec odoo odoo -d <ODOO_DB> -i densamed_sale --stop-after-init
docker compose restart odoo
```
Then give users the *DensaMed Sales / Cashier* group and open the **Сату** app.

## Not included (by design, ask if needed)
Taxes/VAT, accounting invoices, loyalty/discount programs, barcode-scanner
shortcuts, partial returns, and pushing sales back into the `densamed` database
(the bridge is read-only by design).
