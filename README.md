# API Bridge Service

AI-powered webhook transformer. Receives a payload, maps fields per instructions, forwards to target URL.

## Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/skippersayshi/api-bridge-service)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |

## Webhook API

```bash
curl -X POST https://your-app.railway.app/api/bridge \
  -H "Content-Type: application/json" \
  -d '{"source_payload":{"firstName":"John","amount_cents":4900},"target_url":"https://hooks.example.com/crm","mapping_instructions":"Combine names into full_name, convert cents to dollars"}'
```

## Pricing: $29/bridge/month
