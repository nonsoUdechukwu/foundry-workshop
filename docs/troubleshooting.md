# Troubleshooting

## Setup & deployment

??? failure "`InsufficientResourcesAvailable` for Azure AI Search"
    Search capacity in the region is exhausted. Put Search in a nearby region:

    ```bash
    azd env set AZURE_SEARCH_LOCATION northeurope
    azd up
    ```

??? failure "`InsufficientQuota` / model deployment fails"
    Your subscription lacks quota for the model in that region. Either request quota, pick another region
    (`azd env set AZURE_LOCATION <region>`), or lower capacity in `infra/main.bicep` (`chatModelCapacity`).

??? failure "`RequestConflict` / `AnotherOperationInProgress` during `azd up`"
    Two operations touched the Foundry resource at once, usually a deployment and a guardrail policy. Wait a minute
    and run `azd up` again. The template is idempotent.

??? failure "`FlagMustBeSetForRestore` / name already exists"
    A soft-deleted Foundry resource with the same name exists. Purge it (see [Cleanup](cleanup.md)) or use a new
    environment name.

??? failure "`.env` is missing values"
    The `postprovision` hook writes `.env` from azd outputs. Re-run it with `azd hooks run postprovision` or
    `azd env get-values > .env`.

## Authentication

??? failure "`401` / `403` / `PermissionDenied` right after deployment"
    Role assignments can take a few minutes to propagate. Wait, then re-run the cell. If it persists:

    * `az account show`: make sure you're signed into the **same tenant and subscription** you deployed to.
    * Check you have **Foundry User** and **Foundry Project Manager** on the Foundry resource.

??? failure "`DefaultAzureCredential failed to retrieve a token`"
    Run `az login` (in Codespaces: `az login --use-device-code`). With several tenants, add
    `--tenant <tenant-id>`.

## Labs

??? failure "M1: embeddings return `404 DeploymentNotFound`"
    The **project** OpenAI endpoint doesn't serve embeddings. The lab calls the resource-level endpoint
    `https://<resource>.services.ai.azure.com/openai/v1/` instead. Make sure you're running the current notebook.

??? failure "M4: indexing returns 403"
    You need **Search Index Data Contributor** on the Search service (the template assigns it). Wait for role
    propagation. If the agent can't query the index, the **project's managed identity** needs *Search Index Data
    Reader*, which the template also assigns.

??? failure "M10: no rows from the KQL query"
    Telemetry ingestion lags. The cell polls; if it times out, re-run it. You need **Log Analytics Reader** on the
    resource group (template-assigned).

??? failure "M10: no continuous-evaluation runs yet"
    Continuous evaluation runs in the background and results can take a while. Check the eval in the portal
    later. Note the lab's cleanup cell deletes the rule. Skip it if you want to keep scoring.

??? failure "M11: `400` when attaching the guardrail to an agent"
    `RaiConfig` needs the **full ARM resource ID** of the policy (`FOUNDRY_RAI_POLICY_ID` in `.env`), not just
    its name.

??? failure "M11: a harmful prompt wasn't blocked by the filter"
    The model may have refused on its own before the filter's thresholds were reached. That's defence in depth
    working, not a bug. Inspect `content_filter_results` on blocked calls to see which layer acted.

??? failure "M12: `Unsupported risk types` when creating the taxonomy"
    Agent-target taxonomies currently support only `RiskCategory.PROHIBITED_ACTIONS`. Other categories (violence,
    self-harm…) are still covered by the **testing criteria** on the eval.

??? failure "M14: `fineTuningJob field is required`"
    The job needs a training type: `extra_body={"trainingType": "developerTier"}` (or `"globalStandard"`).
    Also check the base model is fine-tunable in your region.

??? failure "M14: job sits in `pending` for a long time"
    Developer-tier jobs queue behind other jobs. Leave it; the lab's default mode only submits the job. Come back
    later and run the remaining cells with `M14_WAIT_FOR_TRAINING=true`.

??? failure "An agent name already exists / unexpected version numbers"
    A previous run stopped before its cleanup cell. Run the lab's cleanup cell, or delete the agent in the portal.

## Still stuck?

[Open an issue](https://github.com/nonsoUdechukwu/foundry-workshop/issues) with the lab number, the failing
cell and the full error.
