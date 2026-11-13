# Simple AWS Lambda layer module

Zips a pre-built directory and publishes it as a Lambda layer version. Building the directory contents
(e.g. `pip install -t <source_dir>/python`) is the caller's job and must happen before `tofu plan`.
