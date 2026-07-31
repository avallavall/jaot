// The REAL prod model `mp_a012f39999f632d5` ("Treasury Cash Flow Odoo 6m") whose
// canvas round-trip silently corrupted it on 2026-07-31: the old deserializer
// dropped every constraint with variables on the RHS to an edge-less `0 <= 0`
// stub and truncated `balance_m1` to `cash_1 == 30000`. Kept verbatim (minus the
// description) as the regression anchor for the linear reader.
import type { OptimizationProblem } from "@/lib/types";

export const TREASURY_PROD: OptimizationProblem = {
  "name": "treasury_cash_flow_odoo_6m",
  "variables": [
    {
      "name": "cash_1",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "cash_2",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "cash_3",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "cash_4",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "cash_5",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "cash_6",
      "type": "continuous",
      "lower_bound": 15000,
      "upper_bound": null
    },
    {
      "name": "borrow_1",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "borrow_2",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "borrow_3",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "borrow_4",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "borrow_5",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "borrow_6",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_1",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_2",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_3",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_4",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_5",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "repay_6",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_1",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_2",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_3",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_4",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_5",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "debt_6",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100000
    },
    {
      "name": "invest_1",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": null
    },
    {
      "name": "invest_2",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": null
    },
    {
      "name": "invest_3",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": null
    },
    {
      "name": "invest_4",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": null
    },
    {
      "name": "invest_5",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": null
    },
    {
      "name": "invest_6",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 0
    },
    {
      "name": "early_pay_supplier_m3",
      "type": "binary",
      "lower_bound": 0,
      "upper_bound": 1
    }
  ],
  "objective": {
    "sense": "maximize",
    "expression": "cash_6"
  },
  "constraints": [
    {
      "name": "balance_m1",
      "expression": "cash_1 == 30000 + 60000 - 50000 + borrow_1 - repay_1 - invest_1 - 0.008*debt_1"
    },
    {
      "name": "balance_m2",
      "expression": "cash_2 == cash_1 + 45000 - 75000 + 1.002*invest_1 - invest_2 + borrow_2 - repay_2 - 0.008*debt_2 - 39200*early_pay_supplier_m3"
    },
    {
      "name": "balance_m3",
      "expression": "cash_3 == cash_2 + 70000 - 115000 + 1.002*invest_2 - invest_3 + borrow_3 - repay_3 - 0.008*debt_3 + 40000*early_pay_supplier_m3"
    },
    {
      "name": "balance_m4",
      "expression": "cash_4 == cash_3 + 55000 - 50000 + 1.002*invest_3 - invest_4 + borrow_4 - repay_4 - 0.008*debt_4"
    },
    {
      "name": "balance_m5",
      "expression": "cash_5 == cash_4 + 90000 - 55000 + 1.002*invest_4 - invest_5 + borrow_5 - repay_5 - 0.008*debt_5"
    },
    {
      "name": "balance_m6",
      "expression": "cash_6 == cash_5 + 65000 - 45000 + 1.002*invest_5 - invest_6 + borrow_6 - repay_6 - 0.008*debt_6"
    },
    {
      "name": "debt_link_m1",
      "expression": "debt_1 == borrow_1 - repay_1"
    },
    {
      "name": "debt_link_m2",
      "expression": "debt_2 == debt_1 + borrow_2 - repay_2"
    },
    {
      "name": "debt_link_m3",
      "expression": "debt_3 == debt_2 + borrow_3 - repay_3"
    },
    {
      "name": "debt_link_m4",
      "expression": "debt_4 == debt_3 + borrow_4 - repay_4"
    },
    {
      "name": "debt_link_m5",
      "expression": "debt_5 == debt_4 + borrow_5 - repay_5"
    },
    {
      "name": "debt_link_m6",
      "expression": "debt_6 == debt_5 + borrow_6 - repay_6"
    },
    {
      "name": "no_repay_m1",
      "expression": "repay_1 == 0"
    },
    {
      "name": "repay_limit_m2",
      "expression": "repay_2 <= debt_1"
    },
    {
      "name": "repay_limit_m3",
      "expression": "repay_3 <= debt_2"
    },
    {
      "name": "repay_limit_m4",
      "expression": "repay_4 <= debt_3"
    },
    {
      "name": "repay_limit_m5",
      "expression": "repay_5 <= debt_4"
    },
    {
      "name": "repay_limit_m6",
      "expression": "repay_6 <= debt_5"
    },
    {
      "name": "close_credit_line",
      "expression": "debt_6 == 0"
    }
  ]
};
