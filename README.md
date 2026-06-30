# f5collector-to-prometheus
Simplified AST/otel collector to prometheus scrape endpoint. 

Forked from [f5devcentral/application-study-tool (branch 9.8)](https://github.com/f5devcentral/application-study-tool/tree/9.8)

## Architecture Enhancements

### Why Sharding was Added
Because the F5 OpenTelemetry collector actively reaches out to poll BIG-IPs (a pull-based telemetry model), all Big-IP metrics would be output to a single prometheus exporter, which in turn will create a huge /metrics endpoint for prometheus to query. 

**Configuration-Based Sharding** solves this. By passing the `--shards X` flag to the initialization script, the system automatically:
1. Distributes your configured BIG-IP targets evenly across multiple distinct `receivers.yaml` files.
2. Generates a `docker-compose.override.yaml` file to dynamically spin up dedicated pairs of scrapers and exporters.
3. Maps each pair to a unique host port (e.g., `9091`, `9092`, `9093`), ensuring external Prometheus instances scrape a cleanly distributed, deduplicated metrics pipeline.

### Batch Processing Improvements
BIG-IPs can generate massive payloads of telemetry data. Pushing these metrics downstream on a per-event basis causes high CPU utilization and network overhead. The pipeline now utilizes the OpenTelemetry `batch` processor to aggregate data before export. By enforcing explicit `send_batch_size`, `send_batch_max_size`, and timeouts, the collector chunks the F5 data into optimized payloads, improving memory stability and dramatically reducing network congestion to the Prometheus exporter.

---

## Otel Collector Setup
Follows a similar setup as the [AST Getting Started Guide](https://f5devcentral.github.io/application-study-tool/getting_started.html#installation) minus a few commands. 

Suggested setup: 

```bash
# Clone the repo
git clone https://github.com/megamattzilla/f5collector-to-prometheus.git
git checkout testing
cd f5collector-to-prometheus

# Edit the following file with device secrets as required (see "Configure Device Secrets" below)
cp .env.device-secrets-example .env.device-secrets

# Edit the default settings for your environment as required
# (see "Configure Default Device Settings" below)
vi ./config/ast_defaults.yaml

# Edit the config file with device / connection info
# (see "Configure Devices To Scrape" below)
vi ./config/bigip_receivers.yaml

# Run the configuration generator with desired number of shards (pairs of f5 otel and generic otel containers)
docker run --rm -it -w /app -v ${PWD}:/app --entrypoint /app/src/bin/init_entrypoint.sh python:3.12.6-slim-bookworm --generate-config --shards 4 

# Start the tool
docker compose up -d