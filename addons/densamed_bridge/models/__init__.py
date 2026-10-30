# -*- coding: utf-8 -*-
from . import densamed_connection
from . import branch_connection          # branches/roles/employees SELECTs (must load before sync)
from . import sync_log                   # log model + job runner (before branch_sync uses it)
from . import densamed_sync
from . import res_company                # x_densamed_branch_id join key
from . import branch_sync                # Deliverable 1 mappers + per-target cron entries
from . import role_group_map             # map table + manual wizard
from . import hr_job
from . import hr_employee
from . import product_template
from . import stock_warehouse
from . import stock_location
from . import stock_lot
from . import branch_views               # branch_id on po/so/picking/quant
from . import branch_dashboard           # SQL view wrapper (_auto=False)
from . import res_config_settings
