# %% [markdown]
# # M14 · Fine-tuning & distillation
#
# **Goal:** make a small, cheap model behave like a big one *for your task*. You'll use a strong **teacher**
# model to label data, fine-tune a small **student** (`gpt-4.1-nano`) on those labels, deploy it and compare.
#
# ```mermaid
# flowchart LR
#   S[Synthetic tickets] --> T[Teacher<br/>gpt-5.4-mini + long prompt]
#   T --> D[(Labelled JSONL)]
#   D --> FT[Fine-tune job<br/>gpt-4.1-nano]
#   FT --> M[Student model]
#   M --> DEP[Deployment]
#   DEP --> C{Compare<br/>teacher vs student}
# ```
#
# **When is distillation worth it?** When you have a narrow, high-volume task, a prompt that has grown long and
# expensive, or latency targets the big model can't hit.
#
# > ⚠️ **Training costs money and time**
# >
# > Training is billed per token and, depending on queue length, can take from tens of minutes to a few hours.
# > The dataset here is tiny (≈60 examples, 1 epoch) to keep cost low. By default the notebook **starts** the
# > job and moves on; set `WAIT_FOR_TRAINING = True` (or come back later) to finish the deploy and compare
# > steps. The fine-tuned deployment uses the **Developer** tier, which has no hourly hosting fee and is deleted
# > automatically after 24 hours.

# %%
import json
import os
import time
from typing import Literal

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

load_dotenv(find_dotenv(usecwd=True), override=True)

ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
TEACHER = os.environ["FOUNDRY_MODEL_NAME"]
STUDENT_BASE = "gpt-4.1-nano-2025-04-14"
WAIT_FOR_TRAINING = os.getenv("M14_WAIT_FOR_TRAINING", "false").lower() == "true"

credential = DefaultAzureCredential()
project = AIProjectClient(endpoint=ENDPOINT, credential=credential)
client = project.get_openai_client()

# %% [markdown]
# ## 1. The task: IT ticket triage
#
# The teacher gets a **long, detailed** prompt with all of Contoso's routing rules. The student will only get a
# one-line prompt — the rules must be learned from the examples.


# %%
class Triage(BaseModel):
    category: Literal["hardware", "software", "access", "network", "security", "other"]
    priority: Literal["P1", "P2", "P3", "P4"]
    team: Literal["service-desk", "endpoint", "identity", "network-ops", "secops"]


TEACHER_PROMPT = """You triage Contoso IT tickets. Rules:
- category: hardware (devices, peripherals), software (apps, installs, licences), access (accounts, passwords,
  permissions, MFA), network (VPN, Wi-Fi, connectivity), security (phishing, malware, data leaks), other.
- priority: P1 = security incident or an outage affecting many people; P2 = one person fully blocked from working;
  P3 = degraded but can work; P4 = request or question.
- team: security → secops; access → identity; network → network-ops; hardware → endpoint;
  software and other → service-desk. EXCEPTION: lost or stolen devices are category security, team secops, P1.
"""
STUDENT_PROMPT = "Triage the Contoso IT ticket. Reply with JSON: category, priority, team."

# %% [markdown]
# ## 2. Generate synthetic tickets
#
# No real data? Ask the teacher to invent varied, realistic inputs (including tricky edge cases).


# %%
class TicketBatch(BaseModel):
    tickets: list[str]


tickets = []
for theme in ("hardware and lost devices", "software and licences", "accounts, passwords and MFA",
              "VPN, Wi-Fi and connectivity", "phishing, malware and suspicious activity", "general questions and requests"):
    batch = client.responses.parse(
        model=TEACHER,
        input=f"Write 10 short, realistic, varied IT helpdesk tickets from Contoso employees about {theme}. "
        "Vary urgency and tone. One or two sentences each.",
        text_format=TicketBatch,
    )
    tickets += batch.output_parsed.tickets
print(len(tickets), "tickets, e.g.:", tickets[:3])

# %% [markdown]
# ## 3. Label them with the teacher

# %%
from concurrent.futures import ThreadPoolExecutor


def teacher_label(ticket):
    result = client.responses.parse(model=TEACHER, instructions=TEACHER_PROMPT, input=ticket, text_format=Triage)
    return result.output_parsed


with ThreadPoolExecutor(max_workers=8) as pool:
    labels = list(pool.map(teacher_label, tickets))

for t, label in list(zip(tickets, labels))[:3]:
    print(f"{label.model_dump_json()}  ← {t}")

# %% [markdown]
# ## 4. Build the training files
#
# Fine-tuning data is **chat-format JSONL**: each line is a conversation ending with the ideal assistant reply.
# Note we train with the *short* student prompt.

# %%
def to_example(ticket, label):
    return {
        "messages": [
            {"role": "system", "content": STUDENT_PROMPT},
            {"role": "user", "content": ticket},
            {"role": "assistant", "content": label.model_dump_json()},
        ]
    }


examples = [to_example(t, lbl) for t, lbl in zip(tickets, labels)]
split = int(len(examples) * 0.8)
os.makedirs("m14-data", exist_ok=True)
for name, rows in (("train", examples[:split]), ("validation", examples[split:])):
    with open(f"m14-data/{name}.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    print(name, len(rows))

with open("m14-data/train.jsonl", "rb") as train, open("m14-data/validation.jsonl", "rb") as validation:
    training_file = client.files.create(file=train, purpose="fine-tune")
    validation_file = client.files.create(file=validation, purpose="fine-tune")
client.files.wait_for_processing(training_file.id)
client.files.wait_for_processing(validation_file.id)
print("Uploaded", training_file.id, validation_file.id)

# %% [markdown]
# ## 5. Start the fine-tuning job

# %%
job = client.fine_tuning.jobs.create(
    model=STUDENT_BASE,
    training_file=training_file.id,
    validation_file=validation_file.id,
    suffix="ticket-triage",
    method={"type": "supervised", "supervised": {"hyperparameters": {"n_epochs": 1}}},
    extra_body={"trainingType": "developerTier"},  # cheapest training tier; use "globalStandard" for faster queues
)
print("Job:", job.id, job.status)
print("Track it in the portal under Fine-tuning, or re-run the next cell later.")

# %% [markdown]
# ## 6. Wait for training (optional)

# %%
fine_tuned_model = None
if WAIT_FOR_TRAINING:
    while (job := client.fine_tuning.jobs.retrieve(job.id)).status not in ("succeeded", "failed", "cancelled"):
        print(time.strftime("%H:%M:%S"), job.status)
        time.sleep(60)
    fine_tuned_model = job.fine_tuned_model
    for event in list(client.fine_tuning.jobs.list_events(job.id, limit=5)):
        print(" ·", event.message)
else:
    job = client.fine_tuning.jobs.retrieve(job.id)
    print("Status:", job.status, "— skipping the wait. Set WAIT_FOR_TRAINING = True to continue.")
print("Fine-tuned model:", fine_tuned_model)

# %% [markdown]
# ## 7. Deploy the student
#
# Fine-tuned models are deployed like any other model, via the management plane. The **DeveloperTier** SKU is made
# for evaluating fine-tunes: no hosting fee, auto-deleted after 24h.

# %%
STUDENT_DEPLOYMENT = "ticket-triage-student"
if fine_tuned_model:
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    from azure.mgmt.cognitiveservices.models import Deployment, DeploymentModel, DeploymentProperties, Sku

    mgmt = CognitiveServicesManagementClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"])
    mgmt.deployments.begin_create_or_update(
        resource_group_name=os.environ["AZURE_RESOURCE_GROUP"],
        account_name=os.environ["FOUNDRY_ACCOUNT_NAME"],
        deployment_name=STUDENT_DEPLOYMENT,
        deployment=Deployment(
            sku=Sku(name="DeveloperTier", capacity=50),
            properties=DeploymentProperties(model=DeploymentModel(format="OpenAI", name=fine_tuned_model, version="1")),
        ),
    ).result()
    print("Deployed", STUDENT_DEPLOYMENT)

# %% [markdown]
# ## 8. Teacher vs student
#
# Score both on the held-out validation tickets: does the student agree with the teacher's labels, and how much
# shorter is its prompt?

# %%
if fine_tuned_model:
    val = examples[split:]
    agree = 0
    for ex in val:
        ticket, expected = ex["messages"][1]["content"], json.loads(ex["messages"][2]["content"])
        out = client.responses.create(model=STUDENT_DEPLOYMENT, instructions=STUDENT_PROMPT, input=ticket)
        try:
            got = json.loads(out.output_text)
        except json.JSONDecodeError:
            got = {}
        agree += got == expected
    print(f"Student matches teacher on {agree}/{len(val)} held-out tickets")
    print(f"Prompt length: teacher {len(TEACHER_PROMPT)} chars vs student {len(STUDENT_PROMPT)} chars")
else:
    print("No fine-tuned model yet — come back when the job has succeeded.")

# %% [markdown]
# > **Expected output (after training):** the student matches the teacher on most held-out tickets — with a
# > one-line prompt and a much smaller model. Use the M9 evaluation tools for a more rigorous comparison.
#
# ## 9. Clean up
#
# Deleting the files is cheap housekeeping. Cancel the job only if you don't intend to come back for it.

# %%
CANCEL_JOB = not WAIT_FOR_TRAINING and os.getenv("M14_CANCEL_JOB", "false").lower() == "true"
if CANCEL_JOB and client.fine_tuning.jobs.retrieve(job.id).status not in ("succeeded", "failed", "cancelled"):
    client.fine_tuning.jobs.cancel(job.id)
    print("Cancelled", job.id)
if fine_tuned_model:
    mgmt.deployments.begin_delete(os.environ["AZURE_RESOURCE_GROUP"], os.environ["FOUNDRY_ACCOUNT_NAME"], STUDENT_DEPLOYMENT).result()
    for f in (training_file, validation_file):
        client.files.delete(f.id)
    print("Deleted deployment and training files")

# %% [markdown]
# ## 🧪 Your turn
#
# 1. Add 20 more tricky tickets (lost phones, phishing that looks like a password reset) and train v2.
# 2. Try **reinforcement fine-tuning** (`method={"type": "reinforcement", …}` with a grader) on `o4-mini`.
# 3. Run the M9 evaluation against both teacher and student deployments.
#
# ## Recap
#
# * **Distillation** = teacher labels + student fine-tune. You trade a one-off training cost for cheaper, faster
#   inference on a narrow task.
# * Training data is chat-format JSONL; keep a validation split.
# * Deploy fine-tunes on the **Developer** tier to evaluate them before paying for production capacity.
#
# Next: **[M15 · Capstone](../15-capstone/)**.
