# Cleanup

Most labs delete the agents, evals and rules they create. The **infrastructure** keeps billing until you remove
it, especially Azure AI Search and any fine-tuned model deployment.

## Remove everything

```bash
azd down --purge
```

`--purge` also permanently deletes the soft-deleted Foundry resource, so its name and quota are freed straight
away.

## Without azd

```bash
source .env
az group delete --name "$AZURE_RESOURCE_GROUP" --yes
az cognitiveservices account purge \
  --name "$FOUNDRY_ACCOUNT_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --location "$AZURE_LOCATION"
```

## Keeping the environment but tidying up

| Leftover | How to remove |
|---|---|
| M4 Search index `contoso-handbook` | Portal → Search service → Indexes → delete, or keep it for M15 |
| M14 deployment `ticket-triage-student` | Run M14's cleanup cell, or Portal → **Models + endpoints** → delete |
| M14 fine-tuning jobs and files | Portal → **Fine-tuning**, or `client.fine_tuning.jobs.cancel(...)` / `client.files.delete(...)` |
| Agents from interrupted labs | Portal → **Agents** → delete |
| Memory stores (M6, M15) | Run the lab's cleanup cell or `project.beta.memory_stores.delete(name)` |

!!! warning "Fine-tuned deployments"
    M14 uses the **DeveloperTier** SKU, which has no hosting fee and is removed automatically after 24 hours. If
    you redeploy a fine-tuned model on **Standard** or **GlobalStandard**, it's billed **per hour while deployed**,
    even if you don't call it. Delete it when you're done.
