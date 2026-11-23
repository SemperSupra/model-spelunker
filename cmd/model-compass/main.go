package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"
)

// MCP / JSON-RPC primitives
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id,omitempty"`
	Result  interface{} `json:"result,omitempty"`
	Error   *RPCError   `json:"error,omitempty"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type CallToolParams struct {
	Name      string          `json:"name"`
	Arguments json.RawMessage `json:"arguments"`
}

// Domain structures
type ModelProfile struct {
	ID                 string   `json:"id"`
	Target             string   `json:"target"` // bigmac, truenas
	ProviderEndpoint   string   `json:"provider_endpoint"`
	MaxContext         int      `json:"max_context"`
	Quantization       string   `json:"quantization"`
	TokPerSec          float64  `json:"tok_per_sec"`
	Uncensored         bool     `json:"uncensored"`
	TaskFamilies       []string `json:"task_families"`
	ToolDialect        string   `json:"tool_dialect"`
	PreferredEditStyle string   `json:"preferred_edit_style"`
	ThinkingMode       string   `json:"thinking_mode"`
	Skills             []string `json:"skills"`
	HarnessFlags       map[string]string `json:"harness_flags"`
	CommonPitfalls     []string `json:"common_pitfalls"`
}

type RecommendRequest struct {
	TaskFamily             string `json:"task_family"`
	EstimatedContextTokens int    `json:"estimated_context_tokens"`
	RequiresUncensored     bool   `json:"requires_uncensored"`
	PreferredTarget        string `json:"preferred_target,omitempty"`
}

type RecommendResponse struct {
	RecommendedModel string            `json:"recommended_model"`
	Target           string            `json:"target"`
	Endpoint         string            `json:"endpoint"`
	AvailableContext int               `json:"available_context"`
	TokPerSec        float64           `json:"tok_per_sec"`
	ToolDialect      string            `json:"tool_dialect"`
	ThinkingMode     string            `json:"thinking_mode"`
	RecommendedSkills []string         `json:"recommended_skills"`
	HarnessFlags     map[string]string `json:"harness_flags"`
	Rationale        string            `json:"rationale"`
}

var Catalog = []ModelProfile{
	{
		ID:                 "qwen3.6-35b",
		Target:             "bigmac",
		ProviderEndpoint:   "http://192.168.178.105:8080/v1",
		MaxContext:         262144,
		Quantization:       "Q8_0",
		TokPerSec:          30.0,
		Uncensored:         false,
		TaskFamilies:       []string{"code_refactor", "large_repo_ingest", "architecture_audit", "general_dev"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "ast_search", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/bigmac-mixed --edit-format diff",
			"hermes":   "-p bigmac -m bigmac-mixed",
			"opencode": "-m bigmac/bigmac-mixed",
		},
		CommonPitfalls: []string{
			"Disable reasoning stream (think: false) during diff application to prevent parse failures.",
			"Use Q8_0 KV cache in unified memory for >100K token sessions.",
		},
	},
	{
		ID:                 "swift-1.5-qwen3.8-27b",
		Target:             "bigmac",
		ProviderEndpoint:   "http://192.168.178.105:8080/v1",
		MaxContext:         262144,
		Quantization:       "Q8_0",
		TokPerSec:          42.0,
		Uncensored:         false,
		TaskFamilies:       []string{"fast_coding", "multi_file_patch", "vision_inspection"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "dflash_speculative_stream", "image_diff"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/swift-1.5-qwen3.8-27b --edit-format diff",
			"hermes":   "-p bigmac -m swift-1.5-qwen3.8-27b",
			"opencode": "-m bigmac/swift-1.5-qwen3.8-27b",
		},
		CommonPitfalls: []string{
			"Leverages DFlash2 speculative decoding window; ensure batch size >= 2048.",
		},
	},
	{
		ID:                 "qwen3.8-27b-uncensored",
		Target:             "bigmac",
		ProviderEndpoint:   "http://192.168.178.105:8080/v1",
		MaxContext:         262144,
		Quantization:       "Q6_K",
		TokPerSec:          27.0,
		Uncensored:         true,
		TaskFamilies:       []string{"red_team", "unfiltered_audit", "reverse_engineering", "vulnerability_remediation"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "binary_analysis", "sandbox_eval"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/qwen3.8-27b-uncensored --edit-format diff",
			"hermes":   "-p bigmac -m qwen3.8-27b-uncensored",
			"opencode": "-m bigmac/qwen3.8-27b-uncensored",
		},
		CommonPitfalls: []string{
			"Abliterated weights bypass corporate refusal filters; enforce external task-scoped isolation.",
		},
	},
	{
		ID:                 "gemma-4-31b-heretic",
		Target:             "bigmac",
		ProviderEndpoint:   "http://192.168.178.105:8080/v1",
		MaxContext:         131072,
		Quantization:       "Q4_K_M",
		TokPerSec:          32.0,
		Uncensored:         true,
		TaskFamilies:       []string{"coder_unfiltered", "complex_refactor", "tool_orchestration"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "whole_file_or_patch",
		ThinkingMode:       "none",
		Skills:             []string{"git", "json_tools", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/gemma-4-31b-heretic --edit-format diff",
			"hermes":   "-p bigmac -m gemma-4-31b-heretic",
			"opencode": "-m bigmac/gemma-4-31b-heretic",
		},
		CommonPitfalls: []string{
			"Do not enclose function parameters in markdown backticks.",
		},
	},
	{
		ID:                 "deepseek-r1:32b",
		Target:             "truenas",
		ProviderEndpoint:   "http://192.168.178.49:30068/v1",
		MaxContext:         32768,
		Quantization:       "Q4_K_M",
		TokPerSec:          29.5,
		Uncensored:         false,
		TaskFamilies:       []string{"deep_reasoning", "algorithmic_proof", "root_cause_diagnosis", "math"},
		ToolDialect:        "chain_of_thought_then_tool",
		PreferredEditStyle: "diff",
		ThinkingMode:       "cot_thinking_tags",
		Skills:             []string{"symbolic_math", "formal_verification", "test_runner"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/deepseek-r1:32b --edit-format diff",
			"hermes":   "-p truenas -m deepseek-r1:32b",
			"opencode": "-m truenas/deepseek-r1:32b",
		},
		CommonPitfalls: []string{
			"Requires sufficient token budget for reasoning traces (<think>...</think>).",
			"In Aider, think traces must not spill into diff chunks.",
		},
	},
	{
		ID:                 "qwen3.8-uncensored:27b",
		Target:             "truenas",
		ProviderEndpoint:   "http://192.168.178.49:30068/v1",
		MaxContext:         32768,
		Quantization:       "Q4_K_M",
		TokPerSec:          34.7,
		Uncensored:         true,
		TaskFamilies:       []string{"red_team", "unfiltered_audit", "rapid_patching"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "sandbox_eval"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3.8-uncensored:27b --edit-format diff",
			"hermes":   "-p truenas -m qwen3.8-uncensored:27b",
			"opencode": "-m truenas/qwen3.8-uncensored:27b",
		},
		CommonPitfalls: []string{
			"Context ceiling is 32768 tokens to ensure 100% GPU residence across dual A5000s.",
		},
	},
	{
		ID:                 "qwen3.5:9b",
		Target:             "truenas",
		ProviderEndpoint:   "http://192.168.178.49:30068/v1",
		MaxContext:         32768,
		Quantization:       "Q4_K_M",
		TokPerSec:          88.5,
		Uncensored:         false,
		TaskFamilies:       []string{"subsecond_edit", "quick_lookup", "lightweight_triage"},
		ToolDialect:        "posix_shell",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "file_finder"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3.5:9b --edit-format diff",
			"hermes":   "-p truenas -m qwen3.5:9b",
			"opencode": "-m truenas/qwen3.5:9b",
		},
		CommonPitfalls: []string{
			"Lower parameter count; not intended for deep multi-module refactoring.",
		},
	},
}

func recommendModel(req RecommendRequest) RecommendResponse {
	var candidates []ModelProfile
	for _, m := range Catalog {
		if req.RequiresUncensored && !m.Uncensored {
			continue
		}
		if req.EstimatedContextTokens > 0 && m.MaxContext < req.EstimatedContextTokens {
			continue
		}
		if req.PreferredTarget != "" && m.Target != req.PreferredTarget {
			continue
		}
		candidates = append(candidates, m)
	}

	if len(candidates) == 0 {
		// Fallback to highest context general model
		return RecommendResponse{
			RecommendedModel: "qwen3.6-35b",
			Target:           "bigmac",
			Endpoint:         "http://192.168.178.105:8080/v1",
			AvailableContext: 262144,
			TokPerSec:        30.0,
			ToolDialect:      "posix_shell_and_unified_diff",
			ThinkingMode:     "off",
			RecommendedSkills: []string{"git", "ast_search"},
			HarnessFlags: map[string]string{
				"aider":  "--model openai/bigmac-mixed --edit-format diff",
				"hermes": "-p bigmac -m bigmac-mixed",
			},
			Rationale: "Fallback to default sovereign workhorse (qwen3.6-35b on BigMac, 256K context).",
		}
	}

	// Score candidates based on task family alignment and speed
	type scoredCandidate struct {
		model ModelProfile
		score int
	}
	var scored []scoredCandidate
	for _, c := range candidates {
		s := 0
		for _, fam := range c.TaskFamilies {
			if strings.EqualFold(fam, req.TaskFamily) {
				s += 100
			}
		}
		if req.EstimatedContextTokens > 65536 && c.MaxContext >= 262144 {
			s += 50
		}
		if req.EstimatedContextTokens <= 32768 && c.TokPerSec > 35.0 {
			s += 30
		}
		scored = append(scored, scoredCandidate{model: c, score: s})
	}

	sort.Slice(scored, func(i, j int) bool {
		return scored[i].score > scored[j].score
	})

	best := scored[0].model
	rationale := fmt.Sprintf("Selected %s on %s: matches task family '%s', supports %d context, runs at ~%.1f tok/s.",
		best.ID, best.Target, req.TaskFamily, best.MaxContext, best.TokPerSec)

	return RecommendResponse{
		RecommendedModel:  best.ID,
		Target:            best.Target,
		Endpoint:          best.ProviderEndpoint,
		AvailableContext:  best.MaxContext,
		TokPerSec:         best.TokPerSec,
		ToolDialect:       best.ToolDialect,
		ThinkingMode:      best.ThinkingMode,
		RecommendedSkills: best.Skills,
		HarnessFlags:      best.HarnessFlags,
		Rationale:         rationale,
	}
}

func getModelHints(modelID string) (ModelProfile, bool) {
	for _, m := range Catalog {
		if strings.EqualFold(m.ID, modelID) {
			return m, true
		}
	}
	return ModelProfile{}, false
}

func checkEndpointHealth(url string, timeout time.Duration) bool {
	client := http.Client{Timeout: timeout}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}

func getLiveCatalog() map[string]interface{} {
	bigmacOK := checkEndpointHealth("http://192.168.178.105:8080/v1/models", 2*time.Second)
	truenasOK := checkEndpointHealth("http://192.168.178.49:30068/api/tags", 2*time.Second)
	strataOK := checkEndpointHealth("http://192.168.178.105:8085/v1/models", 2*time.Second)

	return map[string]interface{}{
		"endpoints": map[string]bool{
			"bigmac_llama_server": bigmacOK,
			"truenas_ollama":      truenasOK,
			"bigmac_strata":       strataOK,
		},
		"catalog_size": len(Catalog),
		"models":       Catalog,
	}
}

func handleMCP(reader io.Reader, writer io.Writer) {
	scanner := bufio.NewScanner(reader)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var req JSONRPCRequest
		if err := json.Unmarshal(line, &req); err != nil {
			continue
		}

		var resp JSONRPCResponse
		resp.JSONRPC = "2.0"
		resp.ID = req.ID

		switch req.Method {
		case "initialize":
			resp.Result = map[string]interface{}{
				"protocolVersion": "2024-11-05",
				"serverInfo": map[string]string{
					"name":    "model-compass",
					"version": "1.0.0",
				},
				"capabilities": map[string]interface{}{
					"tools": map[string]bool{"listChanged": false},
				},
			}
		case "notifications/initialized":
			continue
		case "tools/list":
			resp.Result = map[string]interface{}{
				"tools": []map[string]interface{}{
					{
						"name":        "recommend_model",
						"description": "Recommends the best local sovereign model, target endpoint, and tuned harness flags for a specific task family, context size, and censorship requirements.",
						"inputSchema": map[string]interface{}{
							"type": "object",
							"properties": map[string]interface{}{
								"task_family": map[string]interface{}{
									"type":        "string",
									"description": "Task classification (e.g. 'code_refactor', 'large_repo_ingest', 'red_team', 'deep_reasoning', 'subsecond_edit').",
								},
								"estimated_context_tokens": map[string]interface{}{
									"type":        "integer",
									"description": "Estimated total context tokens needed (up to 262144).",
								},
								"requires_uncensored": map[string]interface{}{
									"type":        "boolean",
									"description": "True if the task requires abliterated/uncensored reasoning without safety filter refusals.",
								},
								"preferred_target": map[string]interface{}{
									"type":        "string",
									"description": "Optional host target constraint: 'bigmac' or 'truenas'.",
								},
							},
							"required": []string{"task_family"},
						},
					},
					{
						"name":        "get_model_hints",
						"description": "Returns model-specific prompt engineering hints, wire tool-calling dialect, recommended skills, and common failure modes.",
						"inputSchema": map[string]interface{}{
							"type": "object",
							"properties": map[string]interface{}{
								"model_name": map[string]interface{}{
									"type":        "string",
									"description": "Identifier of the model (e.g. 'qwen3.6-35b', 'gemma-4-31b-heretic', 'deepseek-r1:32b').",
								},
							},
							"required": []string{"model_name"},
						},
					},
					{
						"name":        "list_available_models",
						"description": "Lists the full catalog of sovereign models, their context limits, tok/s throughput, and live health status across BigMac and TrueNAS.",
						"inputSchema": map[string]interface{}{
							"type": "object",
						},
					},
				},
			}
		case "tools/call":
			var callParams CallToolParams
			if err := json.Unmarshal(req.Params, &callParams); err != nil {
				resp.Error = &RPCError{Code: -32602, Message: "Invalid tool call parameters"}
				break
			}
			switch callParams.Name {
			case "recommend_model":
				var recReq RecommendRequest
				if err := json.Unmarshal(callParams.Arguments, &recReq); err != nil {
					resp.Error = &RPCError{Code: -32602, Message: err.Error()}
					break
				}
				rec := recommendModel(recReq)
				outText, _ := json.MarshalIndent(rec, "", "  ")
				resp.Result = map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": string(outText)}},
				}
			case "get_model_hints":
				var hintReq struct {
					ModelName string `json:"model_name"`
				}
				if err := json.Unmarshal(callParams.Arguments, &hintReq); err != nil {
					resp.Error = &RPCError{Code: -32602, Message: err.Error()}
					break
				}
				hints, ok := getModelHints(hintReq.ModelName)
				if !ok {
					resp.Error = &RPCError{Code: -32602, Message: fmt.Sprintf("Model '%s' not found in catalog", hintReq.ModelName)}
					break
				}
				outText, _ := json.MarshalIndent(hints, "", "  ")
				resp.Result = map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": string(outText)}},
				}
			case "list_available_models":
				live := getLiveCatalog()
				outText, _ := json.MarshalIndent(live, "", "  ")
				resp.Result = map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": string(outText)}},
				}
			default:
				resp.Error = &RPCError{Code: -32601, Message: fmt.Sprintf("Unknown tool: %s", callParams.Name)}
			}
		default:
			resp.Error = &RPCError{Code: -32601, Message: fmt.Sprintf("Unsupported method: %s", req.Method)}
		}

		outBytes, _ := json.Marshal(resp)
		writer.Write(outBytes)
		writer.Write([]byte("\n"))
	}
}

func main() {
	mcpMode := flag.Bool("mcp", false, "Run in MCP JSON-RPC stdio mode")
	recommendMode := flag.String("recommend", "", "Recommend model for task family (e.g. code_refactor, red_team)")
	contextTokens := flag.Int("context", 0, "Estimated context token demand")
	uncensored := flag.Bool("uncensored", false, "Require uncensored/abliterated weights")
	flag.Parse()

	if *mcpMode {
		handleMCP(os.Stdin, os.Stdout)
		return
	}

	if *recommendMode != "" {
		res := recommendModel(RecommendRequest{
			TaskFamily:             *recommendMode,
			EstimatedContextTokens: *contextTokens,
			RequiresUncensored:     *uncensored,
		})
		out, _ := json.MarshalIndent(res, "", "  ")
		fmt.Println(string(out))
		return
	}

	// Default CLI output: display live catalog summary
	fmt.Printf("Model Compass Sovereign Router (v1.0.0)\n")
	fmt.Printf("Registered Models: %d\n\n", len(Catalog))
	for _, m := range Catalog {
		fmt.Printf("• %-26s | Target: %-7s | Ctx: %6d | Tok/s: %4.1f | Uncensored: %-5t | Dialect: %s\n",
			m.ID, m.Target, m.MaxContext, m.TokPerSec, m.Uncensored, m.ToolDialect)
	}
	fmt.Printf("\nUsage:\n  model-compass -recommend <task_family> [-context <tokens>] [-uncensored]\n  model-compass -mcp (Run Model Context Protocol server over stdio)\n")
}
