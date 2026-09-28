# IaC Change Cost Preview

Previews what an infrastructure-as-code change will add to an AWS account and what it will cost per month, before it is deployed. Given a pull request, branch, commit, or pasted CloudFormation template, the skill determines the exact resource additions, modifications, and removals with a CloudFormation change set, cross-checks new resources against the live account topology, and prices every fixed-cost resource with a live AWS Price List API lookup for the target Region.

⚠️ This skill is sample code, not intended for production use without additional review and testing. Users should validate in a non-production environment first.

## Purpose

Autonomous agents and CI pipelines can tell you whether a template is valid and whether it follows best practices. They rarely tell you that the PR you are about to approve adds a Multi-AZ `db.r6g.xlarge`, two NAT gateways, and an OpenSearch domain that together cost more per month than the service they support. This skill puts that number in front of the reviewer while the change is still a diff.

## Key Capabilities

- **Change set first.** Uses `cloudformation:CreateChangeSet` against the target stack so Conditions, Parameters, Mappings, Transforms, and nested stacks are resolved by CloudFormation rather than guessed. Falls back to a static base-versus-head template diff when a change set cannot be created, and labels the preview accordingly.
- **Topology cross-check.** For each addition, looks for a matching live resource outside the stack and flags possible duplicates. For each removal or replacement, lists the live resources that depend on it.
- **Live, per-Region pricing.** Every rate is a `pricing:GetProducts` lookup for the stack's Region on this run. No rate ships with the skill. Unresolved rates are reported as *not priced*, never as `$0.00`.
- **Fixed versus usage-based discipline.** Instance hours, node hours, gateway hours, load balancer hours, provisioned capacity, storage, keys, and secrets are estimated. Requests, bytes, and invocations are named with their unit rate and excluded from the total unless the user supplies a volume.
- **Fixed report layout.** Added, Modified, Removed, Usage-based, Not priced, Totals, Assumptions, Limitations. Readable in chat and in a pull request comment.
- **Read-mostly.** The only write is the change set, which never touches a resource and is deleted when the preview is done.

## Prerequisites

- AWS DevOps Agent with access to the target account and Region.
- A repository integration (GitHub or GitLab) in the Agent Space if you want the skill to read pull requests directly. Without one, paste the base and head templates into the conversation.
- IAM permissions on the role the Agent Space assumes, in addition to the default read-only managed policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ResolveLivePricing",
      "Effect": "Allow",
      "Action": [
        "pricing:GetProducts",
        "pricing:GetAttributeValues"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PreviewChangeSets",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateChangeSet",
        "cloudformation:DescribeChangeSet",
        "cloudformation:DeleteChangeSet",
        "cloudformation:DescribeStacks",
        "cloudformation:GetTemplate"
      ],
      "Resource": "*"
    }
  ]
}
```

Notes:

- `pricing:*` returns public data and does not support resource-level scoping. The Price List API is free and is always called in `us-east-1`; a Region-scoped tool policy must allow that.
- `cloudformation:CreateChangeSet` is a write action even though it changes no resource. If your environment's permission guardrail prompts for approval, the skill explains what it is doing and waits. Without these permissions the skill still works using the static diff, with reduced accuracy.
- For a stack that does not exist yet, CloudFormation creates a `REVIEW_IN_PROGRESS` placeholder; add `cloudformation:DeleteStack` scoped to `arn:aws:cloudformation:*:*:stack/*/*` if you want the skill to clean that up too.
- Sizing signals (log group volume, table size) are not needed by this skill; sizing comes from the template.

## Limitations

- CloudFormation, SAM, and CDK-synthesized templates only. Terraform, Pulumi, and unsynthesized CDK source are reported as out of scope.
- Usage-based charges are never estimated without a user-supplied volume. The preview is a floor for fixed charges, not a total bill.
- A static diff cannot resolve Conditions, `Fn::If`, Transforms, or nested stacks; when the change set path is unavailable the additions list may be incomplete or overstated, and the report says so.
- All rates are public On-Demand. Savings Plans, Reserved Instances, private pricing, and free tier are not applied.
- The skill does not run automatically when a pull request is opened. It runs when asked in chat, or when a scheduled custom agent or a CI job invokes it. See "Triggering on pull requests" below.

## Agent Types

- **Chat tasks** — ask for a preview of a PR, branch, commit, or pasted template.

Select **Generic** when uploading if you want the skill available to all agent types.

## Uploading to AWS DevOps Agent

**Option A: GitHub integration.** Fork or copy this repository and import the skill through the Agent Space GitHub integration. This lets you version and extend `references/pricing-reference.md` with the resource types your templates use.

**Option B: Direct upload.** Zip the skill and upload it as a user-defined skill in the Agent Space console:

```bash
cd skills
zip -r iac-change-cost-preview.zip iac-change-cost-preview/ -i '*.md' '*.txt' '*.json' '*.yaml' '*.yml' -x '*/README.md' '*/CHANGELOG.md' '*/evals/*' '*/.skilleval.yaml'
```

The archive must contain `SKILL.md` at the root of the skill directory with `references/` alongside it.

## Triggering on pull requests

Skills load when the agent judges them relevant to the task at hand; they have no event trigger of their own. Three ways to get a preview onto every pull request:

1. **Release readiness review.** Enable the review for the repository. Whether the review consults space-level skills during its own analysis is not documented; test it by opening a PR that adds a fixed-cost resource and checking the report. If the preview appears, no further wiring is needed.
2. **Scheduled custom agent.** Model on `custom-agents/devops-agent-cost-dashboard`: a custom agent that runs on a schedule, lists open pull requests touching template paths, and invokes this skill for each new or updated one. Posting the result back to the PR requires a repository write tool in the Agent Space.
3. **CI job.** A GitHub Actions workflow on `pull_request` that runs an agent CLI in headless mode with the repository checked out, then posts the output with `gh pr comment`. The skill folder is the same; only the runner's AWS role changes, so keep it read-only plus the change set actions above.

## How to Use This Skill

Sample prompts:

- "Preview the cost impact of PR #142 in acme/payments-infra. The stack is `payments-prod` in account 123456789012, eu-west-1."
- "What resources will this template add to account 123456789012 in us-west-2, and what will they cost per month? Parameters: Environment=prod, InstanceClass=db.r6g.xlarge." (paste the template)
- "Compare the `infra/cluster.yaml` on branch `feature/opensearch` against `main` and tell me the monthly delta for stack `search-prod` in ap-southeast-2."
- "For PR #77, assume 2 TB/month through the new NAT gateways and 50 million Lambda invocations, and include those in the estimate."
- "Does anything in this template already exist in the account under another stack?"

## Skill Contents

```
iac-change-cost-preview/
├── SKILL.md                         # Workflow, definitions, report layout, validation checklist
├── references/
│   └── pricing-reference.md         # Resource type → Price List API lookup, region scoping, units
├── README.md
├── CHANGELOG.md
├── .skilleval.yaml
└── evals/
    └── evals.json
```
