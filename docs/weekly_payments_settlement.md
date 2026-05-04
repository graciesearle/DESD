# Developer Documentation: Weekly Producer Settlements

## Overview
The Weekly Settlement system is designed to provide an idempotent, audit-ready financial pipeline for paying producers. It follows a decoupled architecture, separating the core business logic from the orchestration layer (CLI, Admin, or External Workflow Engines).

## 1. The Settlement Window
The system operates on a strict **Monday 00:00:00 to Sunday 23:59:59** window.
*   Settlements are always generated for the *most recently completed* full week.
*   **Idempotency:** A unique constraint on `(week_start, week_end, producer)` ensures that no producer can be paid twice for the same window.

## 2. Core Components

### Data Models (`orders/models.py`)
*   **`Settlement`**: Records the aggregate financial data for a producer's week (Gross Sales, Commission, Net Payout).
*   **`SettlementLine`**: An immutable audit trail linking a `ProducerOrder` to a `Settlement`. It stores the final `transfer_ref` (either a Stripe `tr_...` ID or a `MOCK-` ID).

### Service Layer (`orders/services/settlement.py`)
The logic is encapsulated in the `run_weekly_settlement(as_of_date, force=False)` service function:

1.  **`resolve_settlement_window(as_of_date)`**: Determines the Mon-Sun bounds.
2.  **Eligibility Filtering**: Selects `ProducerOrders` based on strict financial safety criteria:
    *   **Status:** Must be `DELIVERED`.
    *   **Payment:** Must have a `SUCCESS` status in the linked `Payment` record. This prevents the platform from paying out funds that haven't yet been successfully collected from the customer.
    *   **Uniqueness:** Must not already be linked to an existing `SettlementLine`.
    *   **Soft Deletion:** Must not be marked as `is_deleted`.
3.  **Atomic Execution**: Creates the `Settlement` and `SettlementLines` within a database transaction.
4.  **Stripe Integration**: 
    *   If the producer has a linked Stripe account, it attempts a `stripe.Transfer.create`.
    *   **Demo Mode:** In test mode, if the platform balance is insufficient, it logs a warning and proceeds with a `STRIPE-SIMULATED-...` reference to ensure the demo workflow completes.

## 3. Manual Execution (CLI)
Administrators can trigger settlements manually using the Django management command:

```bash
# Run for the most recently completed week
docker-compose run --rm web python manage.py run_weekly_settlement

# Run for a specific historical window (simulating as if it were a certain date)
docker-compose run --rm web python manage.py run_weekly_settlement --as-of 2026-05-11

# Force a re-run for a window (deletes existing settlement for that window)
docker-compose run --rm web python manage.py run_weekly_settlement --force
```

## 4. Integration with Orchestration (Camunda)
The architecture is intentionally decoupled to support external workflow engines like **Camunda**.

### Suggested Integration Pattern:
1.  **Worker Implementation**: Create a Camunda External Task Worker (e.g., using Python's `camunda-external-task-client`).
2.  **Service Call**: The worker simply imports and calls `run_weekly_settlement(timezone.now().date())`.
3.  **Variable Feedback**: The worker can pass the `result` dictionary (summaries of created/skipped settlements) back to the Camunda process variables for further routing (e.g., sending an aggregate report to an accountant if there are errors).
4.  **Scheduling**: Use a Camunda **Timer Intermediate Catch Event** or a **Start Timer Event** configured with a Cron expression (e.g., `0 0 1 ? * MON *` for every Monday at 1 AM) to trigger the process automatically.

## 5. Security & GDPR
*   **Default Anonymisation:** Payout exports (CSV/PDF) redact customer names by default for GDPR compliance.
*   **Financial Accuracy:** All calculations use Python's `Decimal` with 2-digit quantization (`ROUND_HALF_UP`) to prevent floating-point errors.
