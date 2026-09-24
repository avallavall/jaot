"""Drop the tables and columns of the removed billing layer.

ADR-008 removed billing, credits and payouts from the product. The code lost
its models then, and the database kept the data under the additive rule, which
the owner retired on 2026-08-02. The owner decided on 2026-09-24 to delete it.

Gone: 9 tables (credit_transactions, exchange_rates, featured_placements,
invoices, seller_tos_acceptances, usage_records, withdrawal_schedules,
withdrawals, workspace_credit_pools) and 13 columns on organizations,
model_executions and trigger_runs. No table the code uses points at them.
Production held 34 rows in credit_transactions and none in invoices or
withdrawals.

IRREVERSIBLE FOR THE DATA. The downgrade rebuilds the empty structure exactly as
pg_dump printed it on 2026-09-24, so the chain can go back, but the rows only
come back from the backup the deploy takes before it migrates.

Revision ID: 20260924_drop_billing_tables
Revises: 20260924_drop_billing_beat
"""

from alembic import op

revision = "20260924_drop_billing_tables"
down_revision = "20260924_drop_billing_beat"
branch_labels = None
depends_on = None

#: Dropped in this order: withdrawals points at withdrawal_schedules.
DEAD_TABLES = (
    "withdrawals",
    "withdrawal_schedules",
    "credit_transactions",
    "exchange_rates",
    "featured_placements",
    "invoices",
    "seller_tos_acceptances",
    "usage_records",
    "workspace_credit_pools",
)

#: Column -> its definition, for the downgrade.
DEAD_COLUMNS = {
    "model_executions": {
        "credits_base": "integer",
        "credits_compute": "integer",
        "credits_consumed": "integer",
    },
    "organizations": {
        "billing_email": "character varying",
        "chargeback_count": "integer DEFAULT 0 NOT NULL",
        "currency": "character varying",
        "is_frozen": "boolean DEFAULT false NOT NULL",
        "monthly_quota": "integer",
        "stripe_connect_account_id": "character varying(255)",
        "stripe_connect_onboarding_complete": "boolean DEFAULT false NOT NULL",
        "stripe_customer_id": "character varying(255)",
        "stripe_subscription_id": "character varying(255)",
    },
    "trigger_runs": {"credits_consumed": "integer"},
}

_COLUMN_INDEXES = (
    "CREATE INDEX ix_organizations_stripe_customer_id "
    "ON public.organizations USING btree (stripe_customer_id)",
    "CREATE INDEX ix_organizations_stripe_connect_account_id "
    "ON public.organizations USING btree (stripe_connect_account_id)",
)

#: The structure of the 9 tables, from pg_dump --schema-only on 2026-09-24.
_TABLES_DDL = """
CREATE TABLE public.credit_transactions (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    transaction_type character varying NOT NULL,
    credits_amount integer NOT NULL,
    balance_after integer NOT NULL,
    earned_balance_after integer NOT NULL,
    description character varying NOT NULL,
    reference_type character varying,
    reference_id character varying,
    amount_eur double precision,
    payment_method character varying,
    buyer_organization_id character varying,
    created_at timestamp with time zone NOT NULL,
    created_by character varying,
    available_at timestamp with time zone,
    commission_rate double precision
);

CREATE TABLE public.exchange_rates (
    id integer NOT NULL,
    currency character varying(3) NOT NULL,
    rate_date date NOT NULL,
    rate double precision NOT NULL,
    source character varying NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.exchange_rates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.exchange_rates_id_seq OWNED BY public.exchange_rates.id;

CREATE TABLE public.featured_placements (
    id character varying(64) NOT NULL,
    organization_id character varying(64) NOT NULL,
    placement_type character varying(32) NOT NULL,
    status character varying(16) NOT NULL,
    credits_paid integer NOT NULL,
    duration_days integer NOT NULL,
    starts_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by character varying(64),
    created_by character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE TABLE public.invoices (
    id character varying NOT NULL,
    invoice_number character varying(50) NOT NULL,
    organization_id character varying NOT NULL,
    invoice_type character varying(30) NOT NULL,
    status character varying(20) NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    due_at timestamp with time zone,
    paid_at timestamp with time zone,
    org_name character varying(200) NOT NULL,
    org_email character varying(200),
    org_plan character varying(30) NOT NULL,
    line_items json,
    subtotal_eur double precision NOT NULL,
    tax_rate double precision NOT NULL,
    tax_amount_eur double precision NOT NULL,
    total_eur double precision NOT NULL,
    currency character varying(3) NOT NULL,
    exchange_rate double precision NOT NULL,
    total_local double precision NOT NULL,
    credits_granted integer NOT NULL,
    stripe_invoice_id character varying(200),
    stripe_payment_intent_id character varying(200),
    transaction_id character varying,
    notes character varying(1000)
);

CREATE TABLE public.seller_tos_acceptances (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    tos_version character varying(50) NOT NULL,
    accepted_at timestamp with time zone NOT NULL,
    accepted_by_user_id character varying NOT NULL
);

CREATE TABLE public.usage_records (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    user_id character varying NOT NULL,
    problem_type character varying NOT NULL,
    credits_used integer NOT NULL,
    execution_time_ms double precision NOT NULL,
    status character varying NOT NULL,
    request_metadata json,
    "timestamp" timestamp with time zone NOT NULL
);

CREATE TABLE public.withdrawal_schedules (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    frequency character varying NOT NULL,
    amount_type character varying NOT NULL,
    amount_value double precision,
    min_threshold integer NOT NULL,
    next_execution timestamp with time zone NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE TABLE public.withdrawals (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    schedule_id character varying,
    withdrawal_type character varying NOT NULL,
    credits_amount integer NOT NULL,
    credits_per_eur integer NOT NULL,
    eur_amount double precision NOT NULL,
    target_currency character varying(3) NOT NULL,
    exchange_rate double precision NOT NULL,
    local_amount double precision NOT NULL,
    status character varying NOT NULL,
    processed_at timestamp with time zone,
    failure_reason character varying,
    transaction_reference character varying,
    created_at timestamp with time zone NOT NULL,
    stripe_transfer_id character varying(255)
);

CREATE TABLE public.workspace_credit_pools (
    id character varying(64) NOT NULL,
    workspace_id character varying(64) NOT NULL,
    organization_id character varying(64) NOT NULL,
    allocated_credits integer NOT NULL,
    used_credits integer NOT NULL,
    last_alert_threshold integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.exchange_rates ALTER COLUMN id SET DEFAULT nextval('public.exchange_rates_id_seq'::regclass);

ALTER TABLE ONLY public.credit_transactions
    ADD CONSTRAINT credit_transactions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.exchange_rates
    ADD CONSTRAINT exchange_rates_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.featured_placements
    ADD CONSTRAINT featured_placements_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.seller_tos_acceptances
    ADD CONSTRAINT seller_tos_acceptances_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.exchange_rates
    ADD CONSTRAINT uq_currency_date UNIQUE (currency, rate_date);

ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.withdrawal_schedules
    ADD CONSTRAINT withdrawal_schedules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.withdrawals
    ADD CONSTRAINT withdrawals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspace_credit_pools
    ADD CONSTRAINT workspace_credit_pools_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.workspace_credit_pools
    ADD CONSTRAINT workspace_credit_pools_workspace_id_key UNIQUE (workspace_id);

CREATE INDEX ix_credit_transactions_available_at ON public.credit_transactions USING btree (available_at);

CREATE INDEX ix_credit_transactions_created_at ON public.credit_transactions USING btree (created_at);

CREATE INDEX ix_credit_transactions_organization_id ON public.credit_transactions USING btree (organization_id);

CREATE INDEX ix_credit_transactions_transaction_type ON public.credit_transactions USING btree (transaction_type);

CREATE INDEX ix_credit_txn_org_created ON public.credit_transactions USING btree (organization_id, created_at);

CREATE INDEX ix_exchange_rates_currency ON public.exchange_rates USING btree (currency);

CREATE INDEX ix_exchange_rates_rate_date ON public.exchange_rates USING btree (rate_date);

CREATE INDEX ix_fp_expires_at ON public.featured_placements USING btree (expires_at);

CREATE INDEX ix_fp_organization_id ON public.featured_placements USING btree (organization_id);

CREATE UNIQUE INDEX ix_invoices_invoice_number ON public.invoices USING btree (invoice_number);

CREATE INDEX ix_invoices_organization_id ON public.invoices USING btree (organization_id);

CREATE INDEX ix_seller_tos_acceptances_organization_id ON public.seller_tos_acceptances USING btree (organization_id);

CREATE INDEX ix_usage_records_organization_id ON public.usage_records USING btree (organization_id);

CREATE INDEX ix_usage_records_problem_type ON public.usage_records USING btree (problem_type);

CREATE INDEX ix_usage_records_timestamp ON public.usage_records USING btree ("timestamp");

CREATE INDEX ix_withdrawal_schedules_organization_id ON public.withdrawal_schedules USING btree (organization_id);

CREATE INDEX ix_withdrawals_organization_id ON public.withdrawals USING btree (organization_id);

CREATE INDEX ix_workspace_credit_pools_organization_id ON public.workspace_credit_pools USING btree (organization_id);

CREATE UNIQUE INDEX ix_workspace_credit_pools_workspace_id ON public.workspace_credit_pools USING btree (workspace_id);

CREATE UNIQUE INDEX uq_credit_txn_reference ON public.credit_transactions USING btree (organization_id, transaction_type, reference_type, reference_id) WHERE ((reference_type IS NOT NULL) AND (reference_id IS NOT NULL));

CREATE UNIQUE INDEX ux_credit_txn_refund_solve_task ON public.credit_transactions USING btree (organization_id, reference_id) WHERE (((transaction_type)::text = 'refund'::text) AND ((reference_type)::text = 'solve_task'::text) AND (reference_id IS NOT NULL));

ALTER TABLE ONLY public.credit_transactions
    ADD CONSTRAINT credit_transactions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.featured_placements
    ADD CONSTRAINT featured_placements_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.seller_tos_acceptances
    ADD CONSTRAINT fk_seller_tos_org_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.withdrawal_schedules
    ADD CONSTRAINT withdrawal_schedules_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.withdrawals
    ADD CONSTRAINT withdrawals_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.withdrawals
    ADD CONSTRAINT withdrawals_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.withdrawal_schedules(id);

ALTER TABLE ONLY public.workspace_credit_pools
    ADD CONSTRAINT workspace_credit_pools_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.workspace_credit_pools
    ADD CONSTRAINT workspace_credit_pools_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE CASCADE;
"""


def upgrade() -> None:
    for table in DEAD_TABLES:
        op.execute(f"DROP TABLE IF EXISTS public.{table}")
    for table, columns in DEAD_COLUMNS.items():
        for column in columns:
            op.execute(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    for table, columns in DEAD_COLUMNS.items():
        for column, definition in columns.items():
            op.execute(f"ALTER TABLE public.{table} ADD COLUMN {column} {definition}")
    for statement in _COLUMN_INDEXES:
        op.execute(statement)
    for statement in _TABLES_DDL.split(";"):
        if statement.strip():
            op.execute(statement)
