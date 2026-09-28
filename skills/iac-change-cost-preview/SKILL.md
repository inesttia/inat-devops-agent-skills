---
name: iac-change-cost-preview
description: Previews the monthly cost impact of an infrastructure-as-code change before it is deployed. Use when a user asks what a pull request, branch, commit, or CloudFormation template change will add to, remove from, or resize in an AWS account and what that will cost per month; when reviewing a PR that touches CloudFormation, SAM, or CDK-synthesized templates; or when asked to compare a template against the resources already running in an account. Determines the exact resource additions, modifications, and removals with a CloudFormation change set (falling back to a static template diff), cross-checks new resources against the live account topology for duplicates and blast radius, and prices every fixed-cost resource with a live AWS Price List API lookup for the target Region. Never hardcodes a rate and never estimates usage-based charges without a stated assumption.
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

It works on CloudFormation templates (including SAM templates and CDK-synthesized output) coming from a pull request, a branch, a commit, or pasted directly into the conversation. It produces a fixed-layout preview listing every resource that will be created, modified, or removed, the sizing properties that drive its cost, a live per-Region rate for each fixed-cost resource, and a monthly total. Usage-based charges are named, not guessed.

The skill is read-mostly. Its only write operation is creating a CloudFormation change set, which does not touch any resource and is deleted when the preview is done.

### Execution visibility

Show each `use_aws` call, each rate lookup, and the change set identifier in the response so the reader can audit where every figure came from. A preview whose numbers cannot be traced to a change set entry and a named price dimension is not finished.

## Workflow Checklist

- [ ] Step 0: Collect inputs (change source, target account, Region, stack, parameters)
- [ ] Step 1: Find the changed templates in the change source
- [ ] Step 2: Determine resource changes (change set first, static diff as fallback)
- [ ] Step 3: Cross-check additions and removals against the live topology
- [ ] Step 4: Extract the sizing properties that drive cost
- [ ] Step 5: Resolve a live rate for every fixed-cost resource
- [ ] Step 6: Compute the monthly delta
- [ ] Step 7: Report in the fixed layout
- [ ] Step 8: Validate before reporting

## Definitions

These rules are referenced by name throughout the steps.

**Change-set-first rule.** The authoritative list of what a template change will create, modify, or remove is a CloudFormation change set against the target stack. Conditions, Parameters, Mappings, Transforms, and nested stacks are resolved by CloudFormation, not by reading the template. Use a static diff only when a change set cannot be created, and label the preview accordingly.

**Fixed versus usage-based rule.** A charge is *fixed* when it accrues per hour or per month regardless of traffic: instance hours, node hours, gateway hours, load balancer hours, provisioned capacity, allocated storage, keys, secrets. A charge is *usage-based* when it depends on requests, bytes, invocations, or data processed. Estimate fixed charges. For usage-based charges, print the price dimension and its unit rate and mark the line **usage-based, not estimated**, unless the user has supplied a volume assumption, in which case compute it and print the assumption next to the figure.

**Live rate rule.** Every rate comes from the AWS Price List API on this run, resolved for the target Region, following `references/pricing-reference.md`. Never hardcode a rate, recall one from a pricing page, or carry one over from an earlier preview. If a lookup cannot be resolved, the line is **not priced: rate unavailable** with the reason. Never print `$0.00` for an unresolved rate.

**Region rule.** The target Region is the Region the stack is (or will be) deployed in. Take it from the stack, the pipeline configuration, or the user. Never default to us-east-1 and never use the Agent Space Region. The Pricing API endpoint is always us-east-1; that is a different thing.

**730-hour rule.** A month is 730 hours for hourly charges. State this once in the report.

**Topology rule.** Account topology answers "does this already exist?" and "what depends on this?". It never determines cost. A resource that appears in the template and already exists outside the stack is flagged as a possible duplicate; it is still priced as an addition because CloudFormation will create it.

**Read-only rule.** The skill creates and deletes change sets and reads stacks, templates, resources, and prices. It never executes a change set, never deploys, and never modifies a resource. If the environment's permission guardrail asks for approval to create the change set, explain that it is non-mutating and will be deleted, and wait.

## Step 0: Collect inputs

Resolve these before doing anything else. Ask for whatever is missing.

| Input | How to resolve it |
|---|---|
| Change source | A pull request or merge request reference, a branch or commit, or a template pasted in the conversation. Read repository content through the repository integration tools available in the Agent Space (GitHub or GitLab). If none is configured, ask the user to paste the base and head templates. |
| Target account | From the user or the pipeline configuration in the repository. Never assume the Agent Space account. |
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

### Fallback: static template diff

Parse `Resources` in the base and head templates and classify each logical ID:

- present only in head → **Add**
- present only in base → **Remove**
- present in both with a different `Type` → **Remove** + **Add**
- present in both with different `Properties` → **Modify**

Then apply what can be read statically: skip resources whose `Condition` evaluates to false with the resolved parameters, and treat `Fn::If` branches, `Transform` sections, and `AWS::CloudFormation::Stack` children as unresolved. The report must carry the line **Source of changes: static diff (change set unavailable: <reason>)** and list every unresolved construct, because the additions list may be incomplete or overstated.

## Step 3: Cross-check against the live topology

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
| `AWS::RDS::DBInstance` | `DBInstanceClass`, `Engine`, `MultiAZ`, `AllocatedStorage`, `StorageType`, `Iops`, `LicenseModel` | instance hours, storage GB-month, provisioned IOPS | backup storage beyond free tier, I/O (Aurora) |
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

For a **Modify**, capture the old and new value of each sizing property so the delta can be priced (for example `db.r6g.large → db.r6g.xlarge`).

When a sizing property is a `Ref` or `Fn::FindInMap`, resolve it with the parameters from Step 0. If it cannot be resolved, price nothing for that resource and report **not priced: sizing unresolved (<property>)**.

## Step 5: Resolve live rates

Follow `references/pricing-reference.md` exactly: it gives, per resource type, the Pricing API `ServiceCode`, the filter fields and values, how the target Region is scoped (a `regionCode` filter or a usagetype prefix), and the unit the rate is expressed in.

Rules that apply to every lookup (Live rate rule):

- The Pricing API endpoint is `us-east-1`. The target Region goes into the filters.
- Rate = `pricePerUnit.USD` from `terms.OnDemand → priceDimensions` at `beginRange "0"`. Use the returned `unit`; apply no divisor.
- Exactly one product should match. If several match, add the disambiguating filters listed in the reference (tenancy, operating system, capacity status, deployment option, license model) rather than picking one.
- If zero products match, call `pricing:GetAttributeValues` once for the filter field in question to check the exact spelling of the value for that service, retry with the corrected value, and if it still returns nothing mark the line **not priced: rate unavailable (<ServiceCode>, <field>=<value>, <Region>)**.
- Cache each resolved rate as (ServiceCode, filters, Region) for the rest of the preview; identical resources reuse it.
- Name the price dimension behind every figure in the report: ServiceCode, filter field and value, unit. An unnamed rate is not verified.

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

Use this layout. It is meant to be readable in a pull request comment and in chat.

```text
IaC CHANGE COST PREVIEW
Source:     <repo> PR #<n> (<base>…<head>)  ·  stack <STACK_NAME>  ·  <ACCOUNT_ID>  ·  <REGION>
Changes:    change set <arn or id> (CREATE_COMPLETE, deleted after preview)
            | static diff (change set unavailable: <reason>)
Rates:      live AWS Price List lookups at <timestamp UTC> · 730 h/month · target Region <REGION>

ADDED (n)
  <LogicalId>  <ResourceType>
    sizing:   <InstanceType> · <Engine> · Multi-AZ · 200 GB gp3
    rate:     AmazonRDS instanceType=db.r6g.large databaseEngine=PostgreSQL deploymentOption=Multi-AZ → $x.xxxx/Hrs
              AmazonRDS usagetype=<PREFIX>-RDS:Multi-AZ-GP3-Storage → $x.xx/GB-Mo
    monthly:  $xxx.xx
    topology: possible duplicate of <physical id> (not in stack) | no match in account
  ...

MODIFIED (n)
  <LogicalId>  <ResourceType>  Replacement: <True|False|Conditional>
    change:   DBInstanceClass db.r6g.large → db.r6g.xlarge
    monthly:  +$xxx.xx
    depends:  <dependents from topology, if Replacement is True>

REMOVED (n)
  <LogicalId>  <ResourceType>
    monthly:  −$xxx.xx
    depends:  <dependents from topology>

USAGE-BASED, NOT ESTIMATED (n)
  <LogicalId>  <ResourceType>  <price dimension> $x.xx per <unit>

NOT PRICED (n)
  <LogicalId>  <ResourceType>  rate unavailable | sizing unresolved (<property>)

TOTALS (fixed charges)
  Added        +$x,xxx.xx
  Resized      +$xxx.xx
  Removed      −$xxx.xx
  Net          +$x,xxx.xx / month

ASSUMPTIONS
  - Parameters defaulted: <list> | all parameters supplied
  - OS assumed Linux for <LogicalId> (ImageId not resolvable)
  - <user-supplied volume assumptions, if any>

LIMITATIONS OF THIS PREVIEW
  - <static diff caveats, unresolved constructs, topology tools unavailable, out-of-scope files>
```

Omit an empty section rather than printing `(0)`. Keep resource lines sorted by monthly figure, largest first.

## Step 8: Validate before reporting

Check every item. Fix the report if any fails.

- [ ] The source of changes is stated: change set ID, or static diff with the reason.
- [ ] Every figure in ADDED, MODIFIED, and REMOVED traces to a change set entry (or static diff entry) and a named price dimension with ServiceCode, filter field and value, and unit.
- [ ] No rate was hardcoded, recalled, or reused from a previous preview.
- [ ] No usage-based charge is inside the fixed totals without a stated assumption.
- [ ] No `$0.00` appears for an unresolved rate; those lines are under NOT PRICED.
- [ ] The target Region is the stack's Region, not the Agent Space Region, and it appears in the header.
- [ ] Every parameter that was defaulted is listed under ASSUMPTIONS.
- [ ] The change set has been deleted (and the placeholder stack, for CREATE type).
- [ ] Nothing was deployed or modified.

## Environment Notes

This skill ships with no account, Region, stack, repository, or rate values. Resolve them at run time.

| Value | How to resolve it | Verified when |
|---|---|---|
| Change source | Repository integration tools in the Agent Space, or content pasted by the user | Base and head template bodies are in hand |
| Target account and Region | Pipeline configuration or the user; Region rule | Both appear in the report header |
| Stack name | Pipeline configuration or the user; `DescribeStacks` confirms existence | Change set type (CREATE or UPDATE) is decided |
| Parameters | Pipeline configuration; template defaults otherwise | Defaulted parameters are listed under ASSUMPTIONS |
| Rates | Live Price List lookups per `references/pricing-reference.md` | Each figure names its price dimension |
| Topology | Resource-discovery tools in the Agent Space, if present | Duplicate and dependency lines appear, or the report says topology was unavailable |

## Limitations

- CloudFormation, SAM, and CDK-synthesized templates only. Terraform, Pulumi, and unsynthesized CDK source are reported as out of scope.
- Usage-based charges are never estimated without a user-supplied volume. The preview is a floor for fixed charges, not a total bill.
- A static diff cannot resolve Conditions, `Fn::If`, Transforms, or nested stacks; when the change set path is unavailable the additions list may be incomplete or overstated, and the report says so.
- Savings Plans, Reserved Instances, private pricing, and free tier are not applied; every rate is public On-Demand.
- Creating a change set requires `cloudformation:CreateChangeSet`, `DescribeChangeSet`, `DeleteChangeSet`, `DescribeStacks`, and (for CREATE type) `DeleteStack` on the review placeholder stack. Without them the skill falls back to the static diff.
