# Facilitator guide

Notes for running this workshop with a group, such as a user group, MVP community session, internal training
or hackathon.

## Before the day

- [ ] **Pick a format** (see below) and decide which labs you'll cover.
- [ ] **Check capacity.** Each attendee who deploys their own environment needs quota in the chosen region for
      the chat model (`gpt-5.4-mini`, GlobalStandard) and `text-embedding-3-small`, plus one Azure AI Search
      Basic service. If many attendees share a subscription, lower `chatModelCapacity` or use shared environments.
- [ ] **Do a dry run** of `azd up` and labs 1–2 in the subscription attendees will use. Role assignments,
      policy and region availability are the most common surprises.
- [ ] **Send pre-reqs** a few days early: Azure subscription with *Owner* or *User Access Administrator +
      Contributor*, a GitHub account (for Codespaces) **or** Python 3.10+, Azure CLI and azd locally.
- [ ] **Bookmark** [Troubleshooting](troubleshooting.md) and share the site URL.

## Environment options

| Option | How | Good for |
|---|---|---|
| **Bring your own subscription** | Each attendee runs `azd up` | Experienced audiences, MVP/community sessions |
| **One environment per attendee, pre-provisioned** | Facilitator runs `azd up` per attendee and shares the `.env` | Customer workshops, short sessions |
| **Shared environment** | One deployment, everyone gets *Foundry User* + *Foundry Project Manager* | Large groups with limited quota |

For shared environments, ask attendees to **prefix agent names** with their initials (e.g. `nu-m2-agent`) so
they don't overwrite each other's agents. The M4 index and M11 guardrail policy can be shared.

## Suggested formats

=== "Intro session"

    Platform primer → **M1** → **M2** → **M3** → **M4**. Demo M9 and M11 from a pre-run notebook.

=== "Full day"

    Setup and primer, then **M1–M6** in the morning and **M7, M9, M10, M11, M13** in the afternoon. Close with a
    walkthrough of **M15**.

=== "Two days"

    Day 1: setup, primer, **M1–M8**. Day 2: **M9–M15**, finishing with attendees presenting their capstone
    changes.

=== "Builder track"

    **M2 → M3 → M4 → M5 → M6 → M13 → M15**: everything you need to ship an agent.

=== "Responsible AI track"

    **M2 → M9 → M10 → M11 → M12 → M15**: evaluation, safety and governance.

## Labs that take a while to run

These labs do work in the background. Start them first and explain the concepts while they run.

| Lab | What runs in the background | Tip |
|---|---|---|
| M8 | Deep-research fan-out with web search | Run it once in advance as a demo |
| M9 | Evaluation runs | Start the run, then discuss graders |
| M10 | Continuous evaluation (results lag) | Section 6 polls; move on and come back |
| M12 | Red-team run (hundreds of attack conversations) | Start it early, or show a pre-run report |
| M14 | Fine-tuning job (queue + training) | Default mode only *submits* the job; show results from a pre-run job |

## Running notes

* Labs are independent after M1. If someone falls behind, they can skip ahead; each lab creates and deletes
  its own agents. **M15** needs the M4 index.
* Rendered notebooks on the site show **expected output**. They're useful for attendees who can't run cells.
* Encourage the **🧪 Your turn** exercises. They're where most of the learning happens.

## Afterwards

Remind everyone to **[clean up](cleanup.md)**. Search and model deployments bill while they exist.
