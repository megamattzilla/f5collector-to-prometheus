# f5collector-to-prometheus
simplified AST/otel collector to prometheus scrape endpoint 

Forked from https://github.com/f5devcentral/application-study-tool/tree/9.8 

# Otel Collector Setup
Follows similar setup as https://f5devcentral.github.io/application-study-tool/getting_started.html#installation minus a few commands. 

Suggested setup: 

```
# Clone the repo
git clone https://github.com/megamattzilla/f5collector-to-prometheus.git
cd f5collector-to-prometheus

# Edit the following file with device secrets as required (see "Configure Device Secrets" below)
cp .env.device-secrets-example .env.device-secrets

# Edit the default settings for your environment as required
# (see "Configure Default Device Settings" below)
vi ./config/ast_defaults.yaml

# Edit the config file with device / connection info
# (see "Configure Devices To Scrape" below)
vi ./config/bigip_receivers.yaml

# Run the configuration generator
docker run --rm -it -w /app -v ${PWD}:/app --entrypoint /app/src/bin/init_entrypoint.sh python:3.12.6-slim-bookworm --generate-config

# Start the tool
docker compose up -d
```

## Validation
Once the F5 otel collector is pushing metrics to the generic otel collector via OTLP, you can query the prometheus /metrics endpoint:  
`curl localhost:9099/metrics` 

# Prometheus setup
Point your prometheus instance to this host IP address on port 9099 

Recommended scrape configs to restore label mapping when using a prometheus exporter: 

```
scrape_configs:
  - job_name: 'otel-exporter'
    scrape_interval: 1m
    static_configs:
      - targets: ['otel-collector-prom-exporter:9099']
    metric_relabel_configs:
    # copy exported_instance value to label instance
    - source_labels: [exported_instance]
      target_label: instance
    # remove exported_instance label
    - action: labeldrop
      regex: ^exported_instance$
    # copy exported_instance value to label job
    - source_labels: [exported_job]
      target_label: job
    # remove exported_instance label
    - action: labeldrop
      regex: ^exported_job$
```