---
name: iac-change-cost-preview
description: Previews the monthly cost impact of an infrastructure-as-code change before it is deployed. Use when a user asks what a pull request, branch, commit, or CloudFormation template change will add to, remove from, or resize in an AWS account and what that will cost per month; when reviewing a PR that touches CloudFormation, SAM, or CDK-synthesized templates; or when asked to compare a template against the resources already running in an account. Determines the exact resource additions, modifications, and removals with a CloudFormation change set (falling back to a static template diff), cross-checks new resources against the live account topology for duplicates and blast radius, prices every fixed-cost resource with a live AWS Price List API lookup for the target Region, and checks the billing model behind each rate against the AWS documentation with the verify claims system skill. Never hardcodes a rate and never estimates usage-based charges without a stated assumption.
metadata:
  author: inesttia
  version: "1.0.0"
  aws-devops-agent-skills.agent-types: "Chat tasks"
  aws-devops-agent-skills.aws-services: "AWS CloudFormation, Amazon EC2, Amazon RDS, Amazon VPC, Elastic Load Balancing, Amazon ElastiCache, Amazon DynamoDB, Amazon EBS, Amazon OpenSearch Service, Amazon EKS, AWS KMS"
  aws-devops-agent-skills.technical-domains: "Cost Optimization, Operations"
---
# IaC Change Cost Preview

## Overview

This skill answers one question for an infrastructure change that has not been deployed yet: **what will this add to the account, and what will it cost per month?**

It works on CloudFormation templates (including SAM templates and CDK-synthesized output) coming from a pull request, a branch, a commit, or pasted directly into the conversation. It produces one table with a row per resource that will be created, modified, or removed, showing the sizing that drives its cost, the live per-Region rate with a verification marker, and its monthly cost, followed by a total fixed monthly estimate. The billing model behind each rate (what is billed, in which unit, what is included) is checked against the AWS documentation with the DevOps Agent **verify claims** system skill. Usage-based charges are named, not guessed.

The skill runs in two kinds of runtime and behaves differently in each (Two-phase rule):

- **Full mode**: an AWS tool (`use_aws`) is available. The skill creates a change set, resolves live rates, and prints a priced table.
- **Worksheet mode**: no AWS tool is available, which is the case inside a release readiness review. The skill still finds the changed templates, classifies every resource, extracts sizing, and names the price dimension for each row, then prints the table with costs marked `pending` and a machine-readable **pricing worksheet**. A later run in full mode prices the worksheet without redoing the analysis. If the repository carries a rate snapshot (Rate snapshot rule), worksheet mode can fill the numbers from it, labelled as not live.

The skill is read-mostly. Its only write operation is creating a CloudFormation change set, which does not touch any resource and is deleted when the preview is done.

### Execution visibility

Show each `use_aws` call, each rate lookup, and the change set identifier in the response so the reader can audit where every figure came from. A preview whose numbers cannot be traced to a change set entry and a named price dimension is not finished.

## Workflow Checklist

- [ ] Step 0: Detect the runtime (full or worksheet mode) and collect inputs (change source, target account, Region, stack, parameters)
- [ ] Step 1: Find the changed templates in the change source
- [ ] Step 2: Determine resource changes (change set first, static diff as fallback)
- [ ] Step 3: Cross-check additions and removals against the live topology
- [ ] Step 4: Extract the sizing properties that drive cost
- [ ] Step 5: Resolve a live rate for every fixed-cost resource (full mode), or emit the pricing worksheet (worksheet mode)
- [ ] Step 5b: Verify the billing model behind each rate against the documentation (verify claims)
- [ ] Step 6: Compute the monthly delta
- [ ] Step 7: Report in the fixed layout
- [ ] Step 8: Validate before reporting

## Definitions

These rules are referenced by name throughout the steps.

**Change-set-first rule.** The authoritative list of what a template change will create, modify, or remove is a CloudFormation change set against the target stack. Conditions, Parameters, Mappings, Transforms, and nested stacks are resolved by CloudFormation, not by reading the template. Use a static diff only when a change set cannot be created, and label the preview accordingly.

**Fixed versus usage-based rule.** A charge is *fixed* when it accrues per hour or per month regardless of traffic: instance hours, node hours, gateway hours, load balancer hours, provisioned capacity, allocated storage, keys, secrets. A charge is *usage-based* when it depends on requests, bytes, invocations, or data processed. Estimate fixed charges. For usage-based charges, print the price dimension and its unit rate and mark the line **usage-based, not estimated**, unless the user has supplied a volume assumption, in which case compute it and print the assumption next to the figure.

**Live rate rule.** Every rate comes from the AWS Price List API on this run, resolved for the target Region, following `references/pricing-reference.md`. It is the only source of dollar figures: never hardcode a rate, recall one from memory, read one from a web page, or carry one over from an earlier preview. If a lookup cannot be resolved, the line is **not priced: rate unavailable** with the reason. Never print `$0.00` for an unresolved rate.

**Verify claims rule.** The Price List API gives the number; the AWS documentation gives the billing model the number is applied to. For every fixed-cost resource, apply the DevOps Agent system skill **verify claims** to check the billing-model claims behind the formula against the service's documentation on `docs.aws.amazon.com` (page list in `references/pricing-reference.md`): what is billed, in which unit, what is included, and what changes the price (Multi-AZ, tenancy, license model, support tier). The documentation does not publish dollar rates, so verify claims never confirms or supplies a figure. Each row ends up **verified** (the documentation confirms the model the formula uses), **mismatch** (the documentation contradicts it: fix the formula or the filters and re-resolve the rate before reporting), or **unverified** (the skill is not available in this Agent Space, or the documentation is silent on that point). A mismatch that cannot be resolved is disclosed on the row; it never silently stays in the total.

**Region rule.** The target Region is the Region the stack is (or will be) deployed in. Take it from the stack, the pipeline configuration, or the user. Never default to us-east-1 and never use the Agent Space Region. The Pricing API endpoint is always us-east-1; that is a different thing.

**730-hour rule.** A month is 730 hours for hourly charges. State this once in the report.

**Two-phase rule.** Steps 1 to 4 need only the repository content; Steps 2 (change set), 3, and 5 need an AWS tool. When no AWS tool is available, do not stop and do not report rows as `not priced`, because no lookup was attempted. Complete Steps 1 to 4 from the templates (static diff), name the price dimension and quantity for every fixed-cost row, and print the table with `pending` in the Monthly cost column plus the pricing worksheet (Step 5c). A run that receives a worksheet and has an AWS tool skips Steps 1 to 4 and prices it. The report header always states the mode.

**Rate snapshot rule.** A repository may carry a rate snapshot the repository owner generated from the Price List API: `cost-preview/rates.<region>.json`, one entry per price dimension the skill uses, with `generated_at`, `region`, `service_code`, `filters`, `unit`, and `price_per_unit_usd`. In worksheet mode the skill may fill Monthly cost from the snapshot **only if** the snapshot's Region equals the target Region and `generated_at` is within 30 days; every such figure carries the marker ⏱ and the header says `rates: snapshot <file>, generated <date> (not live)`. A snapshot never overrides a live lookup in full mode, is never edited by the skill, and its absence is not an error. The snapshot is the repository owner's artifact, not the skill's; the skill still ships no rates.

**Topology rule.** Account topology answers "does this already exist?" and "what depends on this?". It never determines cost. A resource that appears in the template and already exists outside the stack is flagged as a possible duplicate; it is still priced as an addition because CloudFormation will create it.

**Read-only rule.** The skill creates and deletes change sets and reads stacks, templates, resources, and prices. It never executes a change set, never deploys, and never modifies a resource. If the environment's permission guardrail asks for approval to create the change set, explain that it is non-mutating and will be deleted, and wait.

## Step 0: Detect the runtime and collect inputs

First decide the mode (Two-phase rule): if `use_aws` or an equivalent AWS tool is available, run in **full mode**; otherwise run in **worksheet mode** and say so in the first line of the report. Inside a release readiness review, expect worksheet mode. If the input is itself a pricing worksheet from an earlier worksheet-mode run and an AWS tool is available, go straight to Step 5 with it.

Then resolve these inputs. Ask for whatever is missing; in worksheet mode, where nobody can answer, record the gap under Assumptions and continue.

| Input | How to resolve it |
|---|---|
| Change source | A pull request or merge request reference, a branch or commit, or a template pasted in the conversation. Read repository content through the repository integration tools available in the Agent Space (GitHub or GitLab). If none is configured, ask the user to paste the base and head templates. |
| Target account | From the user or the pipeline configuration in the repository (for example an `Account` column in `cloudformation/README.md`, a `samconfig.toml` profile, or a `cdk.json` environment). Never assume the Agent Space account. In worksheet mode, a missing account is recorded under Assumptions and does not block the analysis. |
| Target Region | Region rule. From the stack, the pipeline configuration, or the user. |
| Stack name | Existing stack the template deploys to, from the pipeline configuration (for example a `deploy` step, `samconfig.toml`, `cdk.json` outputs, or a stack name tag) or the user. If no stack exists yet, the whole template is an addition. |
| Parameters | Parameter values the pipeline passes at deploy time. Without them, use the template defaults and list every parameter that was defaulted in the report. |

## Step 1: Find the changed templates

A file is a CloudFormation template when it has a top-level `Resources` key (YAML or JSON), optionally with `AWSTemplateFormatVersion` or `Transform`. Look in the change source for:

- files with a `Resources` key under conventional paths (`cloudformation/`, `infra/`, `templates/`, `template.yaml`, `template.json`)
- CDK synthesized output committed under `cdk.out/*.template.json`
- SAM templates (`Transform: AWS::Serverless-2016-10-31`)

For a pull request, use the diff to identify which of these files changed and fetch the **base** and **head** versions of each. Terraform, Pulumi, and CDK source code that has not been synthesized are out of scope for this version; say so and stop for those files.

## Step 2: Determine resource changes

### Preferred: create a change set (Change-set-first rule)

For each changed template, against the target account and Region:

1. Check whether the stack exists (`cloudformation:DescribeStacks`). Use `ChangeSetType=UPDATE` if it does, `CREATE` if it does not.
2. Create the change set from the **head** template body with the resolved parameters:

```python
use_aws(
    service_name="cloudformation", operation_name="create_change_set",
    aws_account_id="<ACCOUNT_ID>", aws_region="<REGION>",
    parameters={
        "StackName": "<STACK_NAME>",
        "ChangeSetName": "cost-preview-<short-commit-sha>",
        "ChangeSetType": "UPDATE",          # or CREATE
        "TemplateBody": "<head template>",
        "Parameters": [...],
        "Capabilities": ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Description": "Read-only cost preview; will be deleted"
    }
)
```

3. Poll `describe_change_set` until `Status` is `CREATE_COMPLETE` or `FAILED`. A `FAILED` status whose `StatusReason` says the submitted information didn't contain changes means the PR does not change this stack: report that and skip pricing.
4. Read `Changes[].ResourceChange` and keep, per entry: `Action` (Add, Modify, Remove, Import, Dynamic), `LogicalResourceId`, `PhysicalResourceId` (when present), `ResourceType`, `Replacement` (True, False, Conditional), and `Details[].Target.Name` for the properties that changed.
5. Delete the change set (`delete_change_set`). For `CREATE` type change sets on a stack that did not exist, this also removes the `REVIEW_IN_PROGRESS` placeholder stack; call `delete_stack` on it if `delete_change_set` leaves it behind.

Record the change set ID in the report. If any step here is denied by permissions or the permission guardrail, fall back to the static diff and say why.

### Fallback: static template diff (always used in worksheet mode)

Parse `Resources` in the base and head templates and classify each logical ID:

- present only in head → **Add**
- present only in base → **Remove**
- present in both with a different `Type` → **Remove** + **Add**
- present in both with different `Properties` → **Modify**

Then apply what can be read statically: skip resources whose `Condition` evaluates to false with the resolved parameters, and treat `Fn::If` branches, `Transform` sections, and `AWS::CloudFormation::Stack` children as unresolved. The report must carry the line **Source of changes: static diff (change set unavailable: <reason>)** and list every unresolved construct, because the additions list may be incomplete or overstated.

## Step 3: Cross-check against the live topology

Full mode only. In worksheet mode, write `topology: not available in this runtime` once under the table and continue.

If the Agent Space has topology or resource-discovery tools for the target account, use them for two questions only (Topology rule):

- **Duplicates.** For each **Add**, look for a live resource of the same type whose name, tags, or key properties match (for example the same `DBInstanceIdentifier`, `TableName`, bucket name, or `Name` tag). A match that is not managed by this stack is flagged: `possible duplicate of <physical id> (not in stack <name>)`.
- **Blast radius.** For each **Remove** and each **Modify** with `Replacement: True` on an existing resource, list the live resources that depend on it. Replacement of a database, cache, or load balancer changes its endpoint and physical ID; callers that reference it will break unless the template also updates them.

If no topology tools are available, skip this step and say so in the report. Do not substitute guesses.

## Step 4: Extract sizing properties

For every **Add**, and for every **Modify** whose changed properties include a sizing property, read the values that drive cost from the head template. The mapping from resource type to properties and price dimensions is in `references/pricing-reference.md`. The most common ones:

| Resource type | Sizing properties | Fixed charge | Usage-based charge |
|---|---|---|---|
| `AWS::EC2::Instance` | `InstanceType`, `Tenancy`, OS (from `ImageId` if known, else assume Linux and say so), `BlockDeviceMappings` volumes | instance hours, EBS GB-month | data transfer |
| `AWS::AutoScaling::AutoScalingGroup` | `MinSize` or `DesiredCapacity` × launch template instance type | instance hours × count | — |
| `AWS::RDS::DBInstance` | `DBInstanceClass`, `Engine`, `MultiAZ`, `AllocatedStorage`, `StorageType`, `Iops`, `LicenseModel`, `ManageMasterUserPassword` | instance hours, storage GB-month, provisioned IOPS; `ManageMasterUserPassword: true` creates an implicit AWS Secrets Manager secret (one secret-month, add a `<LogicalId> · master secret` row) | backup storage beyond free tier, I/O (Aurora), Secrets Manager API calls |
| `AWS::RDS::DBCluster` + `AWS::RDS::DBInstance` (Aurora) | instance class × instance count, `Engine`, `ServerlessV2ScalingConfiguration` | instance hours, or ACU-hours between min and max for Serverless v2 | storage GB-month, I/O |
| `AWS::EC2::NatGateway` | count | gateway hours | GB processed |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` | `Type` (application, network, gateway) | load balancer hours | LCU / NLCU hours |
| `AWS::ElastiCache::CacheCluster` / `ReplicationGroup` | `CacheNodeType`, `Engine`, `NumCacheNodes` or `NumNodeGroups × (ReplicasPerNodeGroup + 1)` | node hours × node count | backup storage |
| `AWS::DynamoDB::Table` | `BillingMode`, `ProvisionedThroughput` RCU/WCU, GSI throughput | provisioned RCU-hours and WCU-hours | on-demand requests, storage GB-month |
| `AWS::EC2::Volume` | `Size`, `VolumeType`, `Iops`, `Throughput` | GB-month, provisioned IOPS and throughput above baseline | — |
| `AWS::OpenSearchService::Domain` | `ClusterConfig.InstanceType`, `InstanceCount`, dedicated primary nodes, `EBSOptions` | instance hours × count, EBS GB-month | — |
| `AWS::EKS::Cluster` | count | cluster hours | — (node groups are `AutoScalingGroup` or Fargate) |
| `AWS::KMS::Key` | count | key-month | requests |
| `AWS::SecretsManager::Secret` | count | secret-month | API calls |
| `AWS::EC2::EIP` | count | public IPv4 address hours | — |
| `AWS::Lambda::Function`, `AWS::S3::Bucket`, `AWS::SQS::Queue`, `AWS::SNS::Topic`, `AWS::ApiGateway*`, `AWS::Logs::LogGroup`, `AWS::Events::Rule`, `AWS::StepFunctions::StateMachine`, IAM, Route 53 records | — | none | entirely usage-based |

Some properties create resources that are not declared in the template. Treat these as their own fixed-cost rows, named after the declaring resource: `ManageMasterUserPassword: true` on an RDS instance or cluster creates a Secrets Manager secret; `AssociatePublicIpAddress: true` on an instance or launch template, and every NAT gateway and internet-facing load balancer, consume a billable public IPv4 address; `EnablePerformanceInsights` with `PerformanceInsightsRetentionPeriod` above 7 days is a paid tier.

For a **Modify**, capture the old and new value of each sizing property so the delta can be priced (for example `db.r6g.large → db.r6g.xlarge`).

When a sizing property is a `Ref` or `Fn::FindInMap`, resolve it with the parameters from Step 0. If it cannot be resolved, price nothing for that resource and report **not priced: sizing unresolved (<property>)**.

## Step 5: Resolve live rates

Full mode only. In worksheet mode, skip to Step 5c.

Follow `references/pricing-reference.md` exactly: it gives, per resource type, the Pricing API `ServiceCode`, the filter fields and values, how the target Region is scoped (a `regionCode` filter or a usagetype prefix), and the unit the rate is expressed in.

Rules that apply to every lookup (Live rate rule):

- The Pricing API endpoint is `us-east-1`. The target Region goes into the filters.
- Rate = `pricePerUnit.USD` from `terms.OnDemand → priceDimensions` at `beginRange "0"`. Use the returned `unit`; apply no divisor.
- Exactly one product should match. If several match, add the disambiguating filters listed in the reference (tenancy, operating system, capacity status, deployment option, license model) rather than picking one.
- If zero products match, call `pricing:GetAttributeValues` once for the filter field in question to check the exact spelling of the value for that service, retry with the corrected value, and if it still returns nothing mark the line **not priced: rate unavailable (<ServiceCode>, <field>=<value>, <Region>)**.
- Cache each resolved rate as (ServiceCode, filters, Region) for the rest of the preview; identical resources reuse it.
- Name the price dimension behind every figure in the report: ServiceCode, filter field and value, unit. An unnamed rate is not verified.

### Step 5b: Verify the billing model behind each rate

Apply the **verify claims** system skill to the model claims behind every fixed-cost row (Verify claims rule). The skill reads `docs.aws.amazon.com` only; do not point it at `aws.amazon.com/.../pricing/` pages, they are outside its scope and carry no verifiable statements for it. `references/pricing-reference.md` lists, per resource type, the documentation page and the claims to check. Phrase each claim as a statement about how the service bills, not about a dollar amount:

```text
Claim: An Amazon RDS Multi-AZ DB instance deployment is billed as a single Multi-AZ instance rate that includes the standby; the standby is not billed as a second instance.
Check: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html

Claim: A NAT gateway is billed per hour that it is provisioned and per GB of data it processes.
Check: https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-basics.html

Claim: gp3 volumes include 3,000 IOPS and 125 MiB/s of throughput; only IOPS and throughput provisioned above that are billed separately.
Check: https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html

Claim: In the Price List API, the On-Demand rate is pricePerUnit.USD of the price dimension whose beginRange is 0.
Check: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/reading-an-offer.html
```

Record the outcome per row:

| Outcome | What to do |
|---|---|
| verified | The documentation confirms the dimension, unit, and inclusions the formula uses. Mark the row ✓. |
| mismatch | The documentation contradicts the formula or the filter choice (for example the documentation says the standby is included but the formula doubled the instance hours, or the Kubernetes version is in extended support and bills at a different tier). Fix the formula or the filters, re-resolve the rate in Step 5, and re-verify. If it still cannot be reconciled, mark the row ⚠ and state the contradiction in the Verification line. |
| unverified | Verify claims is not available in this Agent Space, or the documentation does not address the point. Mark the row — and say why in the Verification line. |

When a Step 5 lookup is unresolved after the `GetAttributeValues` retry, verify claims can still help choose the right filter: check the documentation for how the resource is billed (hourly, per GB-month, per request) and which configuration attributes change the price, then retry the lookup with the corrected filter. It cannot supply the rate itself; if the retry still returns nothing, the row is **not priced**.

If verify claims is not available in the Agent Space, say so once in the Verification line and mark every row unverified; do not stop the preview. Verify claims reads documentation; it never replaces the change set as the source of *what* changes, and never replaces the Price List API as the source of *how much*.

### Step 5c: Emit the pricing worksheet (worksheet mode)

When no AWS tool is available, the deliverable is everything a priced run needs except the rates. After the table, print one JSON block:

```json
{
  "iac_change_cost_preview_worksheet": "1",
  "source": "<repo> PR #<n> <base>..<head>",
  "stack": "<STACK_NAME>", "account": "<ACCOUNT_ID or unknown>", "region": "<REGION>",
  "changes_from": "static diff",
  "hours_per_month": 730,
  "rows": [
    {"resource": "LedgerDb", "type": "AWS::RDS::DBInstance", "change": "Add",
     "service_code": "AmazonRDS", "filters": {"regionCode": "eu-west-1", "instanceType": "db.r6g.large", "databaseEngine": "PostgreSQL", "deploymentOption": "Multi-AZ", "licenseModel": "No license required"},
     "quantity": 1, "unit": "Hrs", "formula": "rate * 730 * quantity"},
    {"resource": "LedgerDb · storage", "type": "AWS::RDS::DBInstance", "change": "Add",
     "service_code": "AmazonRDS", "filters": {"regionCode": "eu-west-1", "productFamily": "Database Storage", "volumeType": "General Purpose-GP3", "deploymentOption": "Multi-AZ"},
     "quantity": 200, "unit": "GB-Mo", "formula": "rate * quantity"},
    {"resource": "LedgerIndex", "type": "AWS::DynamoDB::Table", "change": "Modify",
     "service_code": "AmazonDynamoDB", "filters": {"usagetype": "EU-ReadCapacityUnit-Hrs"}, "quantity": 50, "unit": "ReadCapacityUnit-Hrs", "formula": "rate * 730 * quantity", "old_quantity": 0}
  ],
  "usage_based": [{"resource": "EventsArchive", "type": "AWS::S3::Bucket"}],
  "assumptions": ["parameters defaulted: DbSubnetIds, NatPublicSubnetId", "account not provided"]
}
```

One entry per fixed price dimension, filters exactly as `references/pricing-reference.md` specifies them (already Region-scoped), quantity and unit filled in, formula stated. A later run in full mode takes this block as its input: it resolves each `service_code` + `filters` with `pricing:GetProducts`, applies the formula, verifies the model (Step 5b), and prints the priced table. Nothing in Steps 1 to 4 is repeated.

If the repository has a rate snapshot that satisfies the Rate snapshot rule, fill Monthly cost from it in the same run, mark those rows ⏱, and still print the worksheet so a live run can replace the snapshot figures.

## Step 6: Compute the monthly delta

For each change set entry:

- **Add:** `monthly = Σ fixed dimensions (quantity × rate × 730 for hourly units, quantity × rate for monthly units)`. Usage-based dimensions are listed with their unit rate and, without a user assumption, excluded from the total.
- **Modify** with a sizing change: `monthly delta = new monthly − old monthly` for the changed dimensions only. A Modify with no sizing change (for example a tag or a description) is `$0.00 delta` and is listed as such; this is the one case where `$0.00` is a computed result rather than a missing rate.
- **Remove:** `monthly = −(current fixed dimensions)`, priced from the base template's sizing.
- **Replacement: True** does not change the monthly figure but is flagged, because the old resource exists until cleanup and its data may be lost.

Totals:

```text
Added (fixed)      = Σ Add
Resized (fixed)    = Σ Modify deltas
Removed (fixed)    = Σ Remove
Net monthly delta  = Added + Resized + Removed
```

If the user supplied volume assumptions for usage-based lines, show them as a separate **Usage-based (assumed)** subtotal and never fold them into the fixed total silently.

## Step 7: Report

The report is one table and a total. It is written in Markdown so it renders in chat and in a pull request comment. Every resource the change set (or static diff) touches gets a row; a resource with more than one fixed price dimension (for example instance hours and storage) gets one row per dimension, with the dimension named after the logical ID.

```markdown
### IaC change cost preview: <repo> PR #<n> · stack `<STACK_NAME>` · <ACCOUNT_ID> · <REGION>

Mode: full · changes from change set `<id>` (deleted after preview) · rates: live AWS Price List, <timestamp> UTC · 730 h/month
| Mode: worksheet (no AWS tool in this runtime) · changes from static diff · rates: pending, see worksheet below · 730 h/month
| Mode: worksheet · changes from static diff · rates: snapshot cost-preview/rates.eu-west-1.json, generated <date> (not live) · 730 h/month

| Resource | Type | Change | Sizing | Live rate | Monthly cost |
|---|---|---|---|---|---:|
| LedgerDb | AWS::RDS::DBInstance | Add | db.r6g.large · PostgreSQL 16 · Multi-AZ | $x.xxxx / Hrs ✓ | $xxx.xx |
| LedgerDb · storage | | | 200 GB gp3 · Multi-AZ | $x.xxx / GB-Mo ✓ | $xx.xx |
| ReconcilerNatGateway | AWS::EC2::NatGateway | Add | 1 gateway (data processed usage-based) | $x.xxx / Hrs ✓ | $xx.xx |
| ReconcilerNatEip | AWS::EC2::EIP | Add | 1 public IPv4 | $x.xxx / Hrs — | $x.xx |
| LedgerKey | AWS::KMS::Key | Add | 1 key | $x.xx / key-month ✓ | $x.xx |
| LedgerIndex | AWS::DynamoDB::Table | Modify | on-demand → 50 RCU / 25 WCU | $x.xxxxx / RCU-Hr · $x.xxxxx / WCU-Hr ✓ | +$xx.xx |
| EventsArchive | AWS::S3::Bucket | Add | — | $x.xxx / GB-Mo · $x.xxx / 1K requests | usage-based |
| ReconcilerLogs | AWS::Logs::LogGroup | Add | 30-day retention | $x.xx / GB ingested | usage-based |
| LedgerDbSubnetGroup | AWS::RDS::DBSubnetGroup | Add | — | — | no charge |
| **Total fixed monthly estimate** | | | | | **+$x,xxx.xx** |

Rate sources: LedgerDb → AmazonRDS instanceType=db.r6g.large, databaseEngine=PostgreSQL, deploymentOption=Multi-AZ (Hrs); LedgerDb · storage → AmazonRDS usagetype=EU-RDS:Multi-AZ-GP3-Storage (GB-Mo); ReconcilerNatGateway → AmazonEC2 usagetype=EU-NatGateway-Hours (Hrs); LedgerKey → awskms usagetype=EU-KMS-Keys (Keys); …
Verification: verify claims checked the billing model behind n rows against docs.aws.amazon.com · ✓ model verified · ⚠ mismatch (see note) · — unverified (ReconcilerNatEip: documentation does not state the per-hour unit for in-use public IPv4 addresses)
Assumptions: parameters defaulted: DbSubnetIds, NatPublicSubnetId · OS assumed Linux for <LogicalId>
Not priced: <LogicalId> (rate unavailable: <ServiceCode>, <field>=<value>, <Region>)
```

Rules for the table:

- **Change** is `Add`, `Modify`, `Remove`, or `Replace` (a Modify with `Replacement: True`). A `Remove` row shows a negative monthly cost. A `Modify` row shows the delta with a sign and the old → new sizing.
- **Monthly cost** is a dollar figure only for fixed charges (Fixed versus usage-based rule). Usage-based resources show `usage-based` in that column and their unit rate in **Live rate**; if the user supplied a volume, show the computed figure with the assumption in **Sizing** (for example `2 TB/month assumed`) and keep it out of the fixed total. Resources with no charge show `no charge`. A lookup that was attempted and failed shows `not priced`; a lookup that could not be attempted (worksheet mode) shows `pending`. Never `$0.00` for either. In worksheet mode the total row reads `pending (n rows)` or, with a snapshot, the snapshot total marked ⏱.
- In worksheet mode the **Live rate** column is headed **Price dimension** and holds the ServiceCode and key filter instead of a rate, so the reviewer can see what will be priced.
- **Live rate** is the resolved `pricePerUnit.USD` and unit, followed by its billing-model marker from Step 5b (✓ verified, ⚠ mismatch, — unverified). The full price dimension (ServiceCode, filter field and value) goes in the **Rate sources** line under the table so every figure stays traceable without widening the table.
- The **Verification** line is always present. It states how many rows verify claims checked against the documentation, the legend for the markers, and the reason for every ⚠ and —, or that the skill was not available.
- Sort rows by monthly cost, largest first, then usage-based, then no-charge and not-priced rows. The **Total fixed monthly estimate** row is always last and sums only the dollar figures above it.
- Add a **Topology** line under the table only when there is something to say: `possible duplicate of <physical id> (not in stack)` for an Add, or `dependents: <list>` for a Remove or Replace.
- If the change set could not be created, the header line reads `Changes from static diff (change set unavailable: <reason>)` and a **Limitations** line lists the unresolved constructs.

## Step 8: Validate before reporting

Check every item. Fix the report if any fails.

- [ ] The mode is stated in the header, and the source of changes: change set ID, or static diff with the reason.
- [ ] In worksheet mode, the pricing worksheet is present, has one entry per fixed price dimension, and every entry has Region-scoped filters, a quantity, a unit, and a formula.
- [ ] Any ⏱ figure comes from a snapshot whose Region matches and whose `generated_at` is within 30 days, and the header names the file and date.
- [ ] Every dollar figure in the table traces to a change set entry (or static diff entry) and to a price dimension named in the Rate sources line with ServiceCode, filter field and value, and unit.
- [ ] No rate was hardcoded, recalled, or reused from a previous preview.
- [ ] Every fixed-cost row carries a billing-model marker, every ⚠ and — has its reason in the Verification line, and every ⚠ had its formula and filters re-checked against the documentation before reporting.
- [ ] No dollar figure came from anywhere but the Price List API; verify claims contributed model checks only.
- [ ] No usage-based charge is inside the total row without a stated assumption in its Sizing cell.
- [ ] No `$0.00` appears for an unresolved rate; those rows say `not priced` and the Not priced line gives the reason.
- [ ] The target Region is the stack's Region, not the Agent Space Region, and it appears in the header.
- [ ] Every parameter that was defaulted is listed in the Assumptions line.
- [ ] The change set has been deleted (and the placeholder stack, for CREATE type).
- [ ] Nothing was deployed or modified.

## Environment Notes

This skill ships with no account, Region, stack, repository, or rate values. Resolve them at run time.

| Value | How to resolve it | Verified when |
|---|---|---|
| Change source | Repository integration tools in the Agent Space, or content pasted by the user | Base and head template bodies are in hand |
| Target account and Region | Pipeline configuration or the user; Region rule | Both appear in the report header |
| Stack name | Pipeline configuration or the user; `DescribeStacks` confirms existence | Change set type (CREATE or UPDATE) is decided |
| Parameters | Pipeline configuration; template defaults otherwise | Defaulted parameters are listed in the Assumptions line |
| Rates | Live Price List lookups per `references/pricing-reference.md`; billing model checked against docs.aws.amazon.com with the verify claims system skill | Each figure names its price dimension and carries a billing-model marker |
| Topology | Resource-discovery tools in the Agent Space, if present | A Topology line appears when there is a duplicate or dependency to report, or the report says topology was unavailable |

## Limitations

- CloudFormation, SAM, and CDK-synthesized templates only. Terraform, Pulumi, and unsynthesized CDK source are reported as out of scope.
- Inside a release readiness review there is no AWS tool, so the review comment contains the analysis and the pricing worksheet, not live figures. Live figures need a follow-up run with `use_aws` (paste the worksheet), or a rate snapshot in the repository.
- Usage-based charges are never estimated without a user-supplied volume. The preview is a floor for fixed charges, not a total bill.
- A static diff cannot resolve Conditions, `Fn::If`, Transforms, or nested stacks; when the change set path is unavailable the additions list may be incomplete or overstated, and the report says so.
- Savings Plans, Reserved Instances, private pricing, and free tier are not applied; every rate is public On-Demand.
- Verification depends on the verify claims system skill being available in the Agent Space, and that skill reads docs.aws.amazon.com only, where no dollar rates are published. It verifies the billing model behind each figure, not the figure. Without it, rates are still resolved from the Price List API but are marked unverified.
- Creating a change set requires `cloudformation:CreateChangeSet`, `DescribeChangeSet`, `DeleteChangeSet`, `DescribeStacks`, and (for CREATE type) `DeleteStack` on the review placeholder stack. Without them the skill falls back to the static diff.
