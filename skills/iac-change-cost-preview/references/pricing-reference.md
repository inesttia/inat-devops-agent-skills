# Pricing Reference for IaC Resource Types

Read this file before resolving the first rate in a preview. It maps CloudFormation resource types to the AWS Price List API lookups that price their **fixed** charges, and names the **usage-based** price dimensions that are listed but not estimated.

> **Every rate comes from a live `pricing:GetProducts` call on this run.** Do not recall a rate from memory, a pricing page, or an earlier preview. If a lookup cannot be resolved with the filters below, the line is reported as **not priced: rate unavailable**, never as `$0.00`.

---

## Two different Regions

1. **Pricing API endpoint** — always `us-east-1`.
2. **Target Region** — where the stack is or will be deployed. It goes into the filters: as a `regionCode` filter for attribute-based lookups, or as a usagetype prefix for usagetype-based lookups.

> The target Region comes from the stack, the pipeline configuration, or the user. Never default to us-east-1 and never use the Agent Space Region.

## Reading a rate

- Rate = `pricePerUnit.USD` from `terms.OnDemand → priceDimensions` at `beginRange "0"`.
- Use the `unit` the API returns (`Hrs`, `GB-Mo`, `IOPS-Mo`, `Keys`, `Secrets`, `ACU-Hr`, …). Apply no divisor.
- Hourly units × 730 = monthly. Monthly units × quantity = monthly.
- Exactly one product should match. If several match, add the disambiguating filters listed for that resource; do not pick one arbitrarily.
- If zero products match, call `pricing:GetAttributeValues` once for the suspect field to see the exact value spelling for that service, retry, and if it is still empty report the line as not priced with `<ServiceCode>, <field>=<value>, <Region>`.

```bash
# see the exact values a service uses for a filter field
aws pricing get-attribute-values --service-code <ServiceCode> --attribute-name <field> --region us-east-1
```

## Standard call patterns

```bash
# attribute-based lookup (instances, nodes, domains) — Region as a filter
aws pricing get-products --service-code <ServiceCode> --region us-east-1 \
  --filters '[{"Type":"TERM_MATCH","Field":"regionCode","Value":"<REGION>"},
              {"Type":"TERM_MATCH","Field":"instanceType","Value":"<INSTANCE_TYPE>"},
              ... disambiguating filters ...]'

# usagetype-based lookup (hours, storage, keys) — Region as a prefix on the value
aws pricing get-products --service-code <ServiceCode> --region us-east-1 \
  --filters '[{"Type":"TERM_MATCH","Field":"usagetype","Value":"<PREFIX>-<UsagetypeValue>"}]'
```

`<PREFIX>-` is omitted in us-east-1 (bare value) unless the resource entry below says otherwise.

---

## Fixed-cost resources

### AWS::EC2::Instance · AWS::AutoScaling::AutoScalingGroup (via launch template)

| | |
|---|---|
| ServiceCode | `AmazonEC2` |
| Filters | `regionCode=<REGION>`, `instanceType=<InstanceType>`, `tenancy=Shared` (or `Dedicated`/`Host` from `Tenancy`), `operatingSystem=Linux` (or `Windows`, `RHEL`, `SUSE`), `preInstalledSw=NA`, `capacitystatus=Used`, `licenseModel=No License required` |
| Unit | `Hrs` |
| Monthly | `rate × 730 × instance_count` (ASG: `DesiredCapacity`, else `MinSize`) |
| Notes | The OS comes from the AMI. If `ImageId` cannot be resolved to an OS, assume Linux and list it under ASSUMPTIONS. Windows uses `licenseModel=No License required` as well; SQL Server AMIs need `preInstalledSw=SQL Std` etc. |
| Usage-based | data transfer out |

### AWS::EC2::Volume · `BlockDeviceMappings` on instances

| | |
|---|---|
| ServiceCode | `AmazonEC2` |
| Filters (storage) | `regionCode=<REGION>`, `productFamily=Storage`, `volumeApiName=<VolumeType>` (`gp3`, `gp2`, `io1`, `io2`, `st1`, `sc1`, `standard`) |
| Unit | `GB-Mo` |
| Monthly | `rate × Size` |
| Extra dimensions | gp3 above 3,000 IOPS: `productFamily=System Operation`, `volumeApiName=gp3` (unit `IOPS-Mo`, quantity `Iops − 3000`); gp3 above 125 MB/s: `productFamily=Provisioned Throughput`, `volumeApiName=gp3` (unit `MBps-Mo`, quantity `Throughput − 125`); io1/io2: `productFamily=System Operation`, `volumeApiName=<io1|io2>` (unit `IOPS-Mo`, quantity `Iops`) |
| Alternative | usagetype `<PREFIX>-EBS:VolumeUsage.gp3`, `EBS:VolumeP-IOPS.gp3`, `EBS:VolumeP-Throughput.gp3` (bare in us-east-1) |

### AWS::EC2::NatGateway

| | |
|---|---|
| ServiceCode | `AmazonEC2` |
| Filters | `usagetype=<PREFIX>-NatGateway-Hours` (bare `NatGateway-Hours` in us-east-1) |
| Unit | `Hrs` |
| Monthly | `rate × 730 × gateway_count` |
| Usage-based | `usagetype=<PREFIX>-NatGateway-Bytes`, unit `GB` (data processed) |

### AWS::EC2::EIP · public IPv4 addresses

| | |
|---|---|
| ServiceCode | `AmazonVPC` |
| Filters | `usagetype=<PREFIX>-PublicIPv4:InUseAddress` (bare in us-east-1) |
| Unit | `Hrs` |
| Monthly | `rate × 730 × address_count` |
| Notes | Also applies to the public IP an ALB, NAT gateway, or instance with `AssociatePublicIpAddress` receives. Count one per public IPv4 the template introduces. |

### AWS::ElasticLoadBalancingV2::LoadBalancer

| | |
|---|---|
| ServiceCode | `AWSELB` |
| Filters | `regionCode=<REGION>`, `usagetype=<PREFIX>-LoadBalancerUsage`, `operation=LoadBalancing:Application` (`Type: application`), `LoadBalancing:Network` (`network`), or `LoadBalancing:Gateway` (`gateway`) |
| Unit | `Hrs` |
| Monthly | `rate × 730 × load_balancer_count` |
| Usage-based | `usagetype=<PREFIX>-LCUUsage` with the same `operation` (LCU-hours, NLCU-hours, GLCU-hours) |
| Notes | If the filter set returns more than one product, `pricing:GetAttributeValues` on `usagetype` for `AWSELB` shows the exact prefixed value for the Region. `AWS::ElasticLoadBalancing::LoadBalancer` (Classic) uses `operation=LoadBalancing`. |

### AWS::RDS::DBInstance (non-Aurora)

| | |
|---|---|
| ServiceCode | `AmazonRDS` |
| Filters (instance) | `regionCode=<REGION>`, `instanceType=<DBInstanceClass>`, `databaseEngine=<engine>`, `deploymentOption=<Single-AZ|Multi-AZ>`, `licenseModel=No license required` (MySQL, PostgreSQL, MariaDB) or `License included` / `Bring your own license` (Oracle, SQL Server; also add `databaseEdition`) |
| Engine mapping | `mysql→MySQL`, `postgres→PostgreSQL`, `mariadb→MariaDB`, `oracle-se2→Oracle` + `databaseEdition=Standard Two`, `oracle-ee→Oracle` + `Enterprise`, `sqlserver-ex/web/se/ee→SQL Server` + `Express`/`Web`/`Standard`/`Enterprise` |
| Unit | `Hrs` |
| Monthly | `rate × 730` |
| Filters (storage) | `regionCode=<REGION>`, `productFamily=Database Storage`, `volumeType=<General Purpose-GP3|General Purpose (SSD)|Provisioned IOPS (SSD)|Magnetic>`, `deploymentOption=<Single-AZ|Multi-AZ>`, `databaseEngine=<engine>` if more than one product matches |
| Unit | `GB-Mo` |
| Monthly | `rate × AllocatedStorage` |
| Filters (PIOPS) | `productFamily=Provisioned IOPS`, `deploymentOption`, `regionCode`; unit `IOPS-Mo`; quantity `Iops` (io1) or `Iops − 12000` for gp3 above the baseline on instances that support it |
| Usage-based | backup storage beyond 100% of allocated storage, data transfer |
| Notes | `MultiAZ: true` doubles nothing in the formula: the Multi-AZ product already carries the standby. `deploymentOption=Multi-AZ (readable standbys)` is for `MultiAZ` DB clusters (`AWS::RDS::DBCluster` with `DBClusterInstanceClass`). |

### AWS::RDS::DBCluster + AWS::RDS::DBInstance (Aurora)

| | |
|---|---|
| ServiceCode | `AmazonRDS` |
| Filters (provisioned instance) | `regionCode=<REGION>`, `instanceType=<DBInstanceClass>`, `databaseEngine=Aurora MySQL` or `Aurora PostgreSQL`, `deploymentOption=Single-AZ` (Aurora instances are priced per instance; count each `DBInstance` in the cluster) |
| Unit | `Hrs` |
| Monthly | `rate × 730 × instance_count` |
| Serverless v2 | `usagetype=<PREFIX>-Aurora:ServerlessV2Usage` (bare in us-east-1), unit `ACU-Hr`. Report a range: `MinCapacity × rate × 730` to `MaxCapacity × rate × 730`, labelled as the configured scaling bounds, not a usage estimate. |
| Usage-based | `usagetype=<PREFIX>-Aurora:StorageUsage` (GB-Mo, grows with data), `Aurora:StorageIOUsage` (I/O requests) unless `StorageType: aurora-iopt1` |

### AWS::ElastiCache::CacheCluster · AWS::ElastiCache::ReplicationGroup · AWS::ElastiCache::ServerlessCache

| | |
|---|---|
| ServiceCode | `AmazonElastiCache` |
| Filters | `regionCode=<REGION>`, `instanceType=<CacheNodeType>`, `cacheEngine=<Redis|Valkey|Memcached>` |
| Unit | `Hrs` |
| Node count | `CacheCluster.NumCacheNodes`; `ReplicationGroup`: `NumNodeGroups × (ReplicasPerNodeGroup + 1)`, or `NumCacheClusters` when set |
| Monthly | `rate × 730 × node_count` |
| Serverless | entirely usage-based (`ElastiCache:Serverless-GB-Hrs`, `ElastiCache:Serverless-ECPU`); list, do not estimate |
| Usage-based | backup storage beyond the free allowance |

### AWS::DynamoDB::Table · AWS::DynamoDB::GlobalTable

| | |
|---|---|
| ServiceCode | `AmazonDynamoDB` |
| Filters (PROVISIONED) | `usagetype=<PREFIX>-ReadCapacityUnit-Hrs` and `<PREFIX>-WriteCapacityUnit-Hrs` (bare in us-east-1) |
| Unit | `ReadCapacityUnit-Hrs` / `WriteCapacityUnit-Hrs` |
| Monthly | `(RCU × read_rate + WCU × write_rate) × 730`, summed over the table and every GSI's `ProvisionedThroughput` |
| PAY_PER_REQUEST | entirely usage-based: `usagetype=<PREFIX>-ReadRequestUnits`, `WriteRequestUnits`; list, do not estimate |
| Usage-based | `usagetype=<PREFIX>-TimedStorage-ByteHrs` (GB-Mo, grows with data), streams, backups |
| Notes | Auto scaling (`AWS::ApplicationAutoScaling::ScalableTarget`) makes the provisioned figure a range: price `MinCapacity` and `MaxCapacity` and label it. |

### AWS::OpenSearchService::Domain

| | |
|---|---|
| ServiceCode | `AmazonES` |
| Filters (instances) | `regionCode=<REGION>`, `instanceType=<ClusterConfig.InstanceType>` (for example `r6g.large.search`) |
| Unit | `Hrs` |
| Monthly | `rate × 730 × InstanceCount`, plus the same lookup for `DedicatedMasterType × DedicatedMasterCount` and `WarmType × WarmCount` when enabled |
| Filters (EBS) | `usagetype=<PREFIX>-ES:GP3-Storage` (or `ES:GP2-Storage`, `ES:PIOPS-Storage`), unit `GB-Mo`, quantity `EBSOptions.VolumeSize × data_node_count` |

### AWS::EKS::Cluster

| | |
|---|---|
| ServiceCode | `AmazonEKS` |
| Filters | `usagetype=<PREFIX>-AmazonEKS-Hours:perCluster` |
| Unit | `Hrs` |
| Monthly | `rate × 730` per cluster. Node groups are priced as `AutoScalingGroup` (EC2 entry); Fargate profiles are usage-based. |

### AWS::KMS::Key · AWS::KMS::ReplicaKey

| | |
|---|---|
| ServiceCode | `awskms` |
| Filters | `usagetype=<PREFIX>-KMS-Keys` |
| Unit | `Keys` (per month) |
| Monthly | `rate × key_count` |
| Usage-based | `KMS-Requests` |

### AWS::SecretsManager::Secret

| | |
|---|---|
| ServiceCode | `AWSSecretsManager` |
| Filters | `usagetype=<PREFIX>-AWSSecretsManager-Secrets` |
| Unit | `Secrets` (per month) |
| Monthly | `rate × secret_count` |
| Usage-based | API calls |

### AWS::CloudWatch::Alarm

| | |
|---|---|
| ServiceCode | `AmazonCloudWatch` |
| Filters | `usagetype=<PREFIX>-CW:AlarmMonitorUsage` (standard resolution) or `CW:HighResAlarmMonitorUsage` (`Period < 60`) |
| Unit | `Alarms` (per month) |
| Monthly | `rate × alarm_count` (composite alarms and metric-math alarms with several metrics count each metric) |

---

## Usage-based resources (list, do not estimate)

Print the resource, the price dimension, and its unit rate. Do not compute a monthly figure unless the user supplies a volume, and then print the assumption next to the figure.

| Resource type | ServiceCode | Price dimensions to name |
|---|---|---|
| `AWS::Lambda::Function` | `AWSLambda` | requests (`Request`), duration (`Lambda-GB-Second`, or `Lambda-GB-Second-ARM`) |
| `AWS::S3::Bucket` | `AmazonS3` | storage (`TimedStorage-ByteHrs`), requests (`Requests-Tier1`, `Requests-Tier2`) |
| `AWS::SQS::Queue` | `AWSQueueService` | requests (`Requests-RBP`) |
| `AWS::SNS::Topic` | `AmazonSNS` | requests, notifications per protocol |
| `AWS::ApiGateway::RestApi`, `AWS::ApiGatewayV2::Api` | `AmazonApiGateway` | requests (`ApiGatewayRequest`, `ApiGatewayHttpRequest`) |
| `AWS::Logs::LogGroup` | `AmazonCloudWatch` | ingestion (`DataProcessing-Bytes`), storage (`TimedStorage-ByteHrs`); `RetentionInDays` bounds storage growth |
| `AWS::Events::Rule`, `AWS::Scheduler::Schedule` | `AmazonEventBridge` | events (`Event-64K-Chunks`) |
| `AWS::StepFunctions::StateMachine` | `AmazonStates` | state transitions (Standard), requests and duration (Express) |
| `AWS::Kinesis::Stream` (ON_DEMAND) | `AmazonKinesis` | data in/out; PROVISIONED mode is fixed per shard-hour (`Storage-ShardHour`) |
| `AWS::CloudFront::Distribution` | `AmazonCloudFront` | data transfer, requests |
| `AWS::Route53::HostedZone` | `AmazonRoute53` | fixed per hosted zone-month (`HostedZone`), queries usage-based |
| IAM, `AWS::SSM::Parameter` (Standard), `AWS::EC2::SecurityGroup`, `AWS::EC2::Subnet`, `AWS::EC2::VPC`, `AWS::EC2::RouteTable` | — | no charge |

---

## Region prefix mapping (usagetype-based lookups)

| Region | Prefix |
|---|---|
| us-east-1 | *(omit — bare value)* |
| us-east-2 | USE2 |
| us-west-1 | USW1 |
| us-west-2 | USW2 |
| eu-west-1 | EU |
| eu-west-2 | EUW2 |
| eu-west-3 | EUW3 |
| eu-central-1 | EUC1 |
| eu-central-2 | EUC2 |
| eu-north-1 | EUN1 |
| eu-south-1 | EUS1 |
| eu-south-2 | EUS2 |
| ap-southeast-1 | APS1 |
| ap-southeast-2 | APS2 |
| ap-southeast-3 | APS4 |
| ap-southeast-4 | APS6 |
| ap-southeast-5 | APS7 |
| ap-southeast-6 | APS8 |
| ap-southeast-7 | APS9 |
| ap-northeast-1 | APN1 |
| ap-northeast-2 | APN2 |
| ap-northeast-3 | APN3 |
| ap-south-1 | APS3 |
| ap-south-2 | APS5 |
| ap-east-1 | APE1 |
| ap-east-2 | APE2 |
| sa-east-1 | SAE1 |
| ca-central-1 | CAN1 |
| ca-west-1 | CAN2 |
| me-south-1 | MES1 |
| me-central-1 | MEC1 |
| mx-central-1 | MXC1 |
| af-south-1 | AFS1 |
| il-central-1 | ILC1 |

If a prefixed lookup returns zero products, check the exact value with `pricing:GetAttributeValues --attribute-name usagetype` for that service before reporting the line as not priced; a few services use a different prefix for a Region.

---

## Verifying the billing model with the verify claims system skill

The verify claims system skill reads `docs.aws.amazon.com` only. The documentation does not publish dollar rates, so the skill cannot confirm a figure; it confirms the **billing model** the figure is applied to (SKILL.md Step 5b). For each fixed-cost resource type, check the claims below against the page listed. A confirmed claim marks the row ✓; a contradicted claim means the formula or the filters are wrong and the rate must be re-resolved.

Do not send `aws.amazon.com/.../pricing/` URLs to verify claims; they are outside its allowed domain.

| Resource type | Documentation page | Billing-model claims to verify |
|---|---|---|
| Price List API (all rows) | https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/reading-an-offer.html · https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list-query-api.html | The On-Demand rate is `pricePerUnit.USD` of the price dimension with `beginRange` 0; `GetProducts` filters are exact `TERM_MATCH` on attribute values; the endpoint Region is separate from the priced Region. |
| `AWS::EC2::Instance`, `AutoScalingGroup` | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html · https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/dedicated-instance.html | On-Demand instances are billed per second (Linux) or per hour (Windows) with no long-term commitment; the rate depends on instance type, OS, Region, and tenancy; Dedicated tenancy carries a different rate. |
| `AWS::EC2::Volume`, `BlockDeviceMappings` | https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html · https://docs.aws.amazon.com/ebs/latest/userguide/provisioned-iops.html | gp3 includes 3,000 IOPS and 125 MiB/s baseline; IOPS and throughput above the baseline are billed separately; io1/io2 bill provisioned IOPS in full; storage is billed per GB-month of provisioned size. |
| `AWS::EC2::NatGateway` | https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-basics.html | A NAT gateway is billed per hour it is provisioned and per GB of data processed, plus standard data transfer. |
| `AWS::EC2::EIP`, public IPv4 | https://docs.aws.amazon.com/vpc/latest/userguide/vpc-ip-addressing.html | Public IPv4 addresses (Elastic IPs and auto-assigned) are charged per hour while in use; this applies to NAT gateway and load balancer addresses as well. |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` | https://docs.aws.amazon.com/elasticloadbalancing/latest/application/introduction.html · https://docs.aws.amazon.com/elasticloadbalancing/latest/network/introduction.html | A load balancer is billed per hour (or partial hour) it runs, plus Load Balancer Capacity Units consumed; the hourly component does not depend on traffic. |
| `AWS::RDS::DBInstance` | https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/User_DBInstanceBilling.html · https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html · https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Storage.html | Instance hours are billed per DB instance class, engine, license model, and deployment option; a Multi-AZ deployment is priced as one Multi-AZ instance that includes the standby, not two instances; allocated storage is billed per GB-month at a Multi-AZ rate when Multi-AZ; gp3 provisioned IOPS above the included baseline are billed separately. |
| Aurora `DBCluster` / `DBInstance` | https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.how-it-works.html · https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Overview.StorageReliability.html | Provisioned Aurora bills each DB instance per hour by class; Serverless v2 bills per ACU-hour between the configured minimum and maximum capacity; storage is billed per GB-month as it grows and I/O per request unless the cluster uses I/O-Optimized. |
| `AWS::ElastiCache::*` | https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/CacheNodes.html · https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Replication.html | Node-based clusters bill per node-hour by node type and engine; a replication group bills every primary and replica node; Serverless bills per GB-hour of data stored and per ECPU. |
| `AWS::DynamoDB::Table` | https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/provisioned-capacity-mode.html · https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html | Provisioned mode bills per RCU-hour and WCU-hour for the table and each GSI regardless of use; on-demand mode bills per request unit; storage is billed per GB-month in both modes. |
| `AWS::OpenSearchService::Domain` | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html · https://docs.aws.amazon.com/opensearch-service/latest/developerguide/sizing-domains.html | Data, dedicated master, and warm nodes are each billed per instance-hour by type; EBS storage attached to data nodes is billed per GB-month. |
| `AWS::EKS::Cluster` | https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html | A cluster is billed per hour; clusters on a Kubernetes version in extended support bill at a higher hourly tier than standard support. Check the template's `Version` against the page before choosing the price dimension. |
| `AWS::KMS::Key` | https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html | Customer managed keys incur a monthly fee per key (prorated hourly) plus a per-request charge above the free tier; AWS managed keys do not carry the monthly fee. |
| `AWS::SecretsManager::Secret` | https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html | Each secret is billed per month (prorated) plus per API call. |
| `AWS::CloudWatch::Alarm` | https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_billing.html | Alarms are billed per alarm-month; high-resolution alarms and metric-math alarms with several metrics bill more; composite alarms bill per alarm. |

If a lookup in Step 5 returned zero products, use the same pages to confirm *how* the resource is billed (hourly, GB-month, per request) and which attributes change the price, then correct the filter and retry. The documentation never supplies the rate itself.

---

## Reference links (for readers; not usable by verify claims)

[EC2](https://aws.amazon.com/ec2/pricing/on-demand/) · [EBS](https://aws.amazon.com/ebs/pricing/) · [VPC / NAT / public IPv4](https://aws.amazon.com/vpc/pricing/) · [ELB](https://aws.amazon.com/elasticloadbalancing/pricing/) · [RDS](https://aws.amazon.com/rds/pricing/) · [Aurora](https://aws.amazon.com/rds/aurora/pricing/) · [ElastiCache](https://aws.amazon.com/elasticache/pricing/) · [DynamoDB](https://aws.amazon.com/dynamodb/pricing/provisioned/) · [OpenSearch](https://aws.amazon.com/opensearch-service/pricing/) · [EKS](https://aws.amazon.com/eks/pricing/) · [KMS](https://aws.amazon.com/kms/pricing/) · [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/) · [Price List API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html)
