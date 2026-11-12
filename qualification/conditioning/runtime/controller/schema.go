package main

import _ "embed"

// Source-controlled OpenAPI 3.1 contract, embedded into the same controller binary.
//go:embed openapi.json
var embeddedOpenAPI []byte
