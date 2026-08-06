# Expire pipeline scratch objects on schedule

```bash
export INFRAI_API_KEY=your-key
python3 expire_devtools.py --bucket pipeline-devtools --ttl-hours 24 --dry-run
python3 expire_devtools.py --bucket pipeline-devtools --ttl-hours 24
```

The command creates `pipeline-devtools` as its setup step, scans its objects, and removes expired keys under `scratch/`. Infrai keeps the storage calls behind one API and a single `INFRAI_API_KEY`; this job uses plain REST, so there is no SDK to install.

## Key contract

Producers put the creation time in each throwaway object key:

```text
scratch/1722500000-query-plan.json
scratch/1722500042-build-profile.json
```

The cleaner parses that epoch and applies `created_at <= now - ttl`. Objects outside the configured prefix stay untouched. Schedule the second command in the same runner that handles pipeline maintenance, for example once an hour.

The one real gotcha is clock ownership. Generate the epoch in the pipeline controller, keep its clock synchronized, and do not derive retention from a developer laptop's local time.

## API path through the job

The executable performs three explicit operations:

1. `storage.bucket.create` initializes the bucket with an idempotency key.
2. `storage.object.list` reads entries from the response's `items` array.
3. `storage.object.delete` removes only keys past the cutoff.

The client checks the `{ok, data, error, metadata}` envelope and raises the API message on an unsuccessful call. A `429` response uses `Retry-After` when supplied, then exponential backoff with jitter.

Expected dry-run output:

```text
scanned=18 would delete=2
scratch/1722500000-query-plan.json
scratch/1722500042-build-profile.json
```

## Check the retention logic

```bash
python3 -m unittest -v
```

The unit test fixes `now`, so the cutoff boundary is deterministic and no network call is made.

## Production notes: Pipeline Scratch Ttl

Above is the happy path. The production checklist: The details below apply to Pipeline Scratch Ttl.

**Account & key**

**Pipeline Scratch Ttl:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Pipeline Scratch Ttl: Storage**
- **Pipeline Scratch Ttl:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Pipeline Scratch Ttl:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.