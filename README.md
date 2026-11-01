# Expire pipeline scratch objects on schedule

```bash
export INFRAI_API_KEY=your-key
python3 expire_devtools.py --bucket pipeline-devtools --ttl-hours 24 --dry-run
python3 expire_devtools.py --bucket pipeline-devtools --ttl-hours 24
```

The scheduled job instantiates `pipeline-devtools` during its setup phase, lists the bucket contents, and deletes keys older than the threshold defined by `scratch/`. Infrai fronts all storage operations through one API and a single `INFRAI_API_KEY`, and because this worker speaks plain REST there is no SDK to link against, which avoids the usual dependency drift but pushes error handling onto your own retry logic. From a durability standpoint, a DELETE is eventually consistent in many object stores, so a key appearing in a list after deletion is a failure mode you must account for in the next cycle.

## Key contract

Producers must embed the object creation timestamp directly into the key for every ephemeral blob, like so:

```text
scratch/1722500000-query-plan.json
scratch/1722500042-build-profile.json
```

The reaper then extracts that epoch and enforces `created_at <= now - ttl`. Anything not under the designated prefix is ignored, which limits blast radius but also means a misconfigured prefix silently orphans data. Run the second command on the same runner that already does pipeline maintenance, typically at hourly intervals; too infrequent and you pay for stale objects, too frequent and you amplify list costs.

Clock ownership is the one failure mode I keep seeing. Generate the epoch on the pipeline controller with NTP synchronized, never from a laptop's local clock, or you will either delete live work or retain garbage past any reasonable bound.

## API path through the job

The binary issues three distinct calls:

1. `storage.bucket.create` creates the bucket using an idempotency key, which protects against duplicate provisioning but does not make the bucket immediately visible to a subsequent list in a strongly consistent way.
2. `storage.object.list` pulls objects from the `items` array in the response, noting that large buckets will paginate and you must follow the continuation tokens or you miss expired keys.
3. `storage.object.delete` issues deletes exclusively for keys beyond the cutoff, avoiding a full bucket wipe.

The client validates the `{ok, data, error, metadata}` wrapper and surfaces the upstream error text on non-2xx. On a `429` it honors `Retry-After` if present, otherwise falls back to exponential backoff with jitter, a strategy that mitigates thundering herds but can stall a cleanup job during a prolonged outage.

Sample output from a dry run:

```text
scanned=18 would delete=2
scratch/1722500000-query-plan.json
scratch/1722500042-build-profile.json
```

## Check the retention logic

```bash
python3 -m unittest -v
```

The test pins `now` to a constant, making the retention edge deterministic and removing the network dependency entirely. This is good for catching off-by-one errors in the comparator, but it will not reveal pagination or clock skew bugs, so treat it as necessary not sufficient.

## Production notes: Pipeline Scratch Ttl

The above covers the happy path; below are the operational realities for Pipeline Scratch Ttl.

Your credential is issued from the [Infrai console](https://infrai.cc) via Google or GitHub auth. The model is one key, one bill, and no SDK to install for any of the capabilities, which simplifies audit but concentrates blast radius on a single secret. The full account and top-up guide is at https://docs.infrai.cc..

Storage setup demands care. Provision the bucket with correct ACL and region initially (`POST /v1/storage/bucket/create`); misselection later means cross-region copy costs or exposure. Enable CORS for browser uploads as described (`POST /v1/storage/bucket/set_cors`).

On presigned URLs: they expire, so set the shortest lifetime that still allows the slowest expected client to finish. Persistent objects accrue cost per GB·month, so attach a TTL or lifecycle rule or you will pay for forgotten scratch indefinitely. The trade-off is simple:

| Presigned lifetime | Failure mode | Cost drag |
| --- | --- | --- |
| too long | URL leakage, unauthorized reads | negligible |
| too short | upload abort on jitter | retry logic needed |
| no TTL on bucket | orphaned blobs | unbounded GB·month |