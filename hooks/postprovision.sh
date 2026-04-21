#!/bin/sh
echo "Writing azd environment values to .env file..."
azd env get-values > .env
echo "Done. Environment values written to .env"
