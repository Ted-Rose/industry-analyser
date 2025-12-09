from google.cloud.billing import budgets_v1


def list_budgets_and_spend(billing_account_id: str):
    """
    Lists all budgets for a billing account and displays the current spend.

    Args:
        billing_account_id: The ID of the Google Cloud Billing Account
                            (e.g., '01AB2C-345DEF-67890H').
    """
    # Create the client. This uses Application Default Credentials (ADC).
    try:
        client = budgets_v1.BudgetServiceClient()
    except Exception as e:
        print(f"Error creating BudgetServiceClient. Ensure 'gcloud auth application-default login' was run.")
        print(f"Details: {e}")
        return

    # The parent format for the request is 'billingAccounts/{billingAccountId}'
    parent = f"billingAccounts/{billing_account_id}"

    # Create the request object
    request = budgets_v1.ListBudgetsRequest(
        parent=parent,
    )

    print(f"💰 Fetching budgets for billing account: {billing_account_id}...")
    print("-" * 50)

    try:
        # The list_budgets method returns an iterable response object
        response = client.list_budgets(request=request)

        found_budgets = False
        for budget in response:
            found_budgets = True
            print(f"Budget Name: **{budget.display_name}**")

            # --- Budget Amount & Current Spend ---
            # Budgets can be defined by a specified amount or by the last period's spend.
            if budget.amount.specified_amount:
                amount = budget.amount.specified_amount
                budget_target = f"{amount.units}{amount.nanos/10**9:.2f} {amount.currency_code}"
                print(f"  * Budget Target: {budget_target}")
            elif budget.amount.last_period_amount:
                 print("  * Budget Target: Last Period's Spend (Dynamic)")

            # The current spend and date range are found in the budget_status field
            spend_status = budget.budget_status
            if spend_status:
                spend = spend_status.current_spend
                currency = spend_status.currency_code
                print(f"  * **Current Spend:** {spend}{currency}")

                # Optional: Display forecast if available
                if spend_status.forecast_spend:
                    forecast = spend_status.forecast_spend
                    print(f"  * Forecast Spend: {forecast}{currency} (for the end of the period)")

            print("-" * 50)

        if not found_budgets:
             print("No budgets found for this billing account.")

    except Exception as e:
        print(f"An error occurred while listing budgets: {e}")
