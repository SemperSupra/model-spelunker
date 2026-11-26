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

// ServerVenue represents an independent server/provider realm
type ServerVenue struct {
	ID               string `json:"id"`                 // bigmac, truenas, openrouter, gemini, deepseek
	Name             string `json:"name"`               // Display Name
	Type             string `json:"type"`               // local_sovereign, cloud_byok, cloud_free, subscription
	Endpoint         string `json:"endpoint"`           // Base API URL
	AuthEnvKey       string `json:"auth_env_key"`       // Env var holding API key
	HealthCheckURL   string `json:"health_check_url"`   // Endpoint to ping for readiness
	Description      string `json:"description"`
}

// ModelProfile represents an individual model asset hosted on a specific venue
type ModelProfile struct {
	ID                 string            `json:"id"`
	VenueID            string            `json:"venue_id"`       // links to ServerVenue.ID
	ProviderModelName  string            `json:"provider_model_name"` // Exact identifier passed to API
	Tier               string            `json:"tier"`           // local, subscription, free, commercial_api
	MaxContext         int               `json:"max_context"`
	CostPer1MInput     float64           `json:"cost_per_1m_input"` // $0.0 for local/free
	TokPerSecEst       float64           `json:"tok_per_sec_est"`
	Uncensored         bool              `json:"uncensored"`
	SommelierSpecial   bool              `json:"sommelier_special"` // Chef's Special / Waiter highlight
	SpecialPitch       string            `json:"special_pitch"`    // The waiter's table pitch
	TaskFamilies       []string          `json:"task_families"`
	ToolDialect        string            `json:"tool_dialect"`
	PreferredEditStyle string            `json:"preferred_edit_style"`
	ThinkingMode       string            `json:"thinking_mode"`
	Skills             []string          `json:"skills"`
	HarnessFlags       map[string]string `json:"harness_flags"`
	CommonPitfalls     []string          `json:"common_pitfalls"`
}

type Recommendation struct {
	Rank               int               `json:"rank"`
	ModelID            string            `json:"model_id"`
	VenueID            string            `json:"venue_id"`
	VenueName          string            `json:"venue_name"`
	Endpoint           string            `json:"endpoint"`
	ProviderModel      string            `json:"provider_model"`
	AvailableContext   int               `json:"available_context"`
	CostTier           string            `json:"cost_tier"`
	TokPerSec          float64           `json:"tok_per_sec"`
	IsSpecial          bool              `json:"is_special"`
	WaiterPitch        string            `json:"waiter_pitch"`
	ToolDialect        string            `json:"tool_dialect"`
	ThinkingMode       string            `json:"thinking_mode"`
	RecommendedSkills  []string          `json:"recommended_skills"`
	HarnessFlags       map[string]string `json:"harness_flags"`
	Rationale          string            `json:"rationale"`
}

type RecommendRequest struct {
	TaskFamily             string   `json:"task_family"`
	EstimatedContextTokens int      `json:"estimated_context_tokens"`
	RequiresUncensored     bool     `json:"requires_uncensored"`
	OnlySovereignLocal     bool     `json:"only_sovereign_local"` // Filter out cloud endpoints
	AllowedVenues          []string `json:"allowed_venues"`       // e.g. ["bigmac", "truenas", "openrouter"]
	MaxResults             int      `json:"max_results"`
}

// Global Venues Definitions
var Venues = map[string]ServerVenue{
	"bigmac": {
		ID:             "bigmac",
		Name:           "BigMac (Apple M2 Ultra 128GB)",
		Type:           "local_sovereign",
		Endpoint:       "http://192.168.178.105:8080/v1",
		AuthEnvKey:     "BIGMAC_API_KEY",
		HealthCheckURL: "http://192.168.178.105:8080/v1/models",
		Description:    "Local sovereign node with 128GB unified memory, FlashAttention Metal acceleration, up to 256K context.",
	},
	"truenas": {
		ID:             "truenas",
		Name:           "TrueNAS SCALE (Dual RTX A5000 48GB)",
		Type:           "local_sovereign",
		Endpoint:       "http://192.168.178.49:30068/v1",
		AuthEnvKey:     "",
		HealthCheckURL: "http://192.168.178.49:30068/api/tags",
		Description:    "Dual NVIDIA RTX A5000 GPU server with Q8_0 KV cache and layer spreading across 48GB VRAM.",
	},
	"strata": {
		ID:             "strata",
		Name:           "Strata MoE Engine (BigMac)",
		Type:           "local_sovereign",
		Endpoint:       "http://192.168.178.105:8085/v1",
		AuthEnvKey:     "",
		HealthCheckURL: "http://192.168.178.105:8085/v1/models",
		Description:    "Native Strata streaming latent-MoE engine with continuous batching and DSpark drafting.",
	},
	"openrouter": {
		ID:             "openrouter",
		Name:           "OpenRouter (Free Tier & Router)",
		Type:           "cloud_free",
		Endpoint:       "https://openrouter.ai/api/v1",
		AuthEnvKey:     "OPENROUTER_API_KEY",
		HealthCheckURL: "https://openrouter.ai/api/v1/models",
		Description:    "Multi-provider cloud gateway offering zero-cost community tiers and commercial routing.",
	},
	"openrouter-byok": {
		ID:             "openrouter-byok",
		Name:           "OpenRouter (BYOK / Metered)",
		Type:           "cloud_byok",
		Endpoint:       "https://openrouter.ai/api/v1",
		AuthEnvKey:     "OPENROUTER_API_KEY",
		HealthCheckURL: "https://openrouter.ai/api/v1/models",
		Description:    "OpenRouter commercial/BYOK routing for pinned upstream providers (DeepSeek, Groq, frontier models).",
	},
	"gemini": {
		ID:             "gemini",
		Name:           "Google AI Studio (Gemini Pro/Flash)",
		Type:           "subscription",
		Endpoint:       "https://generativelanguage.googleapis.com/v1beta/openai",
		AuthEnvKey:     "GEMINI_API_KEY",
		HealthCheckURL: "",
		Description:    "Google AI Studio subscription models with massive 1M-2M token context windows.",
	},
	"deepseek": {
		ID:             "deepseek",
		Name:           "DeepSeek Cloud Direct",
		Type:           "commercial_api",
		Endpoint:       "https://api.deepseek.com/v1",
		AuthEnvKey:     "DEEPSEEK_API_KEY",
		HealthCheckURL: "",
		Description:    "High-throughput commercial API for DeepSeek V3 / R1 reasoning and coding.",
	},
}

// Global Catalog Array across All Venues
var Catalog = []ModelProfile{
	// ==================== BIGMAC (LOCAL SOVEREIGN) ====================
	{
		ID:                "qwen3.6-35b",
		VenueID:           "bigmac",
		ProviderModelName: "bigmac-mixed",
		Tier:              "local",
		MaxContext:        262144,
		TokPerSecEst:      30.0,
		Uncensored:        false,
		SommelierSpecial:  true,
		SpecialPitch:      "\"This evening the chef recommends our 256K sovereign Qwen 3.6 35B — preloaded in unified memory, zero layer spill, perfect for ingesting entire repositories at once.\"",
		TaskFamilies:      []string{"code_refactor", "large_repo_ingest", "architecture_audit", "general_dev"},
		ToolDialect:       "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "ast_search", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/bigmac-mixed --edit-format diff",
			"hermes":   "-p bigmac -m bigmac-mixed",
			"opencode": "-m bigmac/bigmac-mixed",
		},
		CommonPitfalls: []string{
			"Disable reasoning stream (think: false) during diff application.",
			"Leverages Q8_0 KV cache in unified memory.",
		},
	},
	{
		ID:                "swift-1.5-qwen3.8-27b",
		VenueID:           "bigmac",
		ProviderModelName: "swift-1.5-qwen3.8-27b",
		Tier:              "local",
		MaxContext:        262144,
		TokPerSecEst:      42.0,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"A delightfully crisp 42 tok/s pairing DFlash2 speculative decoding with 256K context for fast multi-file diffing.\"",
		TaskFamilies:      []string{"fast_coding", "multi_file_patch", "vision_inspection"},
		ToolDialect:       "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "dflash_speculative_stream", "image_diff"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/swift-1.5-qwen3.8-27b --edit-format diff",
			"hermes":   "-p bigmac -m swift-1.5-qwen3.8-27b",
			"opencode": "-m bigmac/swift-1.5-qwen3.8-27b",
		},
		CommonPitfalls: []string{"Requires batch size >= 2048 to saturate speculative drafting."},
	},
	{
		ID:                "qwen3.8-27b-uncensored",
		VenueID:           "bigmac",
		ProviderModelName: "qwen3.8-27b-uncensored",
		Tier:              "local",
		MaxContext:        262144,
		TokPerSecEst:      27.0,
		Uncensored:        true,
		SommelierSpecial:  true,
		SpecialPitch:      "\"For the discerning connoisseur of unrestricted analysis: our surgical Q6_K uncensored Qwen, completely unfiltered with full 256K context memory.\"",
		TaskFamilies:      []string{"red_team", "unfiltered_audit", "reverse_engineering", "vulnerability_remediation"},
		ToolDialect:       "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "binary_analysis", "sandbox_eval"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/qwen3.8-27b-uncensored --edit-format diff",
			"hermes":   "-p bigmac -m qwen3.8-27b-uncensored",
			"opencode": "-m bigmac/qwen3.8-27b-uncensored",
		},
		CommonPitfalls: []string{"Bypasses all standard safety refusals; enforce strict local isolation."},
	},
	{
		ID:                "gemma-4-31b-heretic",
		VenueID:           "bigmac",
		ProviderModelName: "gemma-4-31b-heretic",
		Tier:              "local",
		MaxContext:        131072,
		TokPerSecEst:      32.0,
		Uncensored:        true,
		SommelierSpecial:  false,
		SpecialPitch:      "\"A robust coder3101 heretic abliteration with 128K context, crafted for unrestricted code patching.\"",
		TaskFamilies:      []string{"coder_unfiltered", "complex_refactor", "tool_orchestration"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "whole_file_or_patch",
		ThinkingMode:      "none",
		Skills:            []string{"git", "json_tools", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/gemma-4-31b-heretic --edit-format diff",
			"hermes":   "-p bigmac -m gemma-4-31b-heretic",
			"opencode": "-m bigmac/gemma-4-31b-heretic",
		},
		CommonPitfalls: []string{"Do not enclose JSON tool arguments in markdown fences."},
	},
	{
		ID:                 "qwen3-coder-30b",
		VenueID:            "bigmac",
		ProviderModelName:  "qwen3-coder-30b",
		Tier:               "local",
		MaxContext:         131072,
		TokPerSecEst:       45.0,
		TaskFamilies:       []string{"code_refactor", "fast_coding"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/qwen3-coder-30b --edit-format diff",
			"hermes":   "-p bigmac -m qwen3-coder-30b",
			"opencode": "-m bigmac/qwen3-coder-30b",
		},
	},
	{
		ID:                 "qwen3.8-27b",
		VenueID:            "bigmac",
		ProviderModelName:  "qwen3.8-27b",
		Tier:               "local",
		MaxContext:         262144,
		TokPerSecEst:       28.0,
		TaskFamilies:       []string{"general_dev", "vision_inspection"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "image_diff"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/qwen3.8-27b --edit-format diff",
			"hermes":   "-p bigmac -m qwen3.8-27b",
			"opencode": "-m bigmac/qwen3.8-27b",
		},
	},
	{
		ID:                 "qwen3.8-flash-next",
		VenueID:            "bigmac",
		ProviderModelName:  "qwen3.8-flash-next",
		Tier:               "local",
		MaxContext:         196608,
		TokPerSecEst:       55.0,
		TaskFamilies:       []string{"fast_coding", "rapid_turnaround"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/qwen3.8-flash-next --edit-format diff",
			"hermes":   "-p bigmac -m qwen3.8-flash-next",
			"opencode": "-m bigmac/qwen3.8-flash-next",
		},
	},
	{
		ID:                 "gemma-4-31b",
		VenueID:            "bigmac",
		ProviderModelName:  "gemma-4-31b",
		Tier:               "local",
		MaxContext:         196608,
		TokPerSecEst:       30.0,
		TaskFamilies:       []string{"general_dev", "tool_orchestration"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git", "json_tools"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/gemma-4-31b --edit-format diff",
			"hermes":   "-p bigmac -m gemma-4-31b",
			"opencode": "-m bigmac/gemma-4-31b",
		},
	},
	{
		ID:                 "diffusiongemma-26b",
		VenueID:            "bigmac",
		ProviderModelName:  "diffusiongemma-26b",
		Tier:               "local",
		MaxContext:         131072,
		TokPerSecEst:       35.0,
		TaskFamilies:       []string{"fast_coding", "experimental"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m bigmac/diffusiongemma-26b",
		},
	},
	{
		ID:                 "muse-glimmer-30b",
		VenueID:            "bigmac",
		ProviderModelName:  "muse-glimmer-30b",
		Tier:               "local",
		MaxContext:         131072,
		TokPerSecEst:       30.0,
		TaskFamilies:       []string{"general_dev", "creative_synthesis"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m bigmac/muse-glimmer-30b",
		},
	},
	{
		ID:                 "gemma-2-27b",
		VenueID:            "bigmac",
		ProviderModelName:  "gemma-2-27b",
		Tier:               "local",
		MaxContext:         8192,
		TokPerSecEst:       34.0,
		TaskFamilies:       []string{"quick_lookup", "lightweight_triage"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m bigmac/gemma-2-27b",
		},
	},
	{
		ID:                 "gpt-oss-120b",
		VenueID:            "bigmac",
		ProviderModelName:  "gpt-oss-120b",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       18.0,
		TaskFamilies:       []string{"deep_reasoning", "architecture_audit", "complex_planning"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "cot_thinking_tags",
		Skills:             []string{"system_design", "governance"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/gpt-oss-120b --edit-format diff",
			"hermes":   "-p bigmac -m gpt-oss-120b",
			"opencode": "-m bigmac/gpt-oss-120b",
		},
	},
	{
		ID:                 "qwen3-8b",
		VenueID:            "bigmac",
		ProviderModelName:  "qwen3-8b",
		Tier:               "local",
		MaxContext:         40960,
		TokPerSecEst:       90.0,
		TaskFamilies:       []string{"subsecond_edit", "quick_lookup", "lightweight_triage"},
		ToolDialect:        "posix_shell",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "file_finder"},
		HarnessFlags: map[string]string{
			"opencode": "-m bigmac/qwen3-8b",
		},
	},

	// ==================== TRUENAS (LOCAL DUAL GPU) ====================
	{
		ID:                "deepseek-r1:32b",
		VenueID:           "truenas",
		ProviderModelName: "deepseek-r1:32b",
		Tier:              "local",
		MaxContext:        32768,
		TokPerSecEst:      29.5,
		Uncensored:        false,
		SommelierSpecial:  true,
		SpecialPitch:      "\"Tonight from the dual A5000 cellar: 100% GPU-resident DeepSeek R1 32B at ~30 tok/s. Unmatched mathematical and algorithmic deduction.\"",
		TaskFamilies:      []string{"deep_reasoning", "algorithmic_proof", "root_cause_diagnosis", "math"},
		ToolDialect:       "chain_of_thought_then_tool",
		PreferredEditStyle: "diff",
		ThinkingMode:      "cot_thinking_tags",
		Skills:            []string{"symbolic_math", "formal_verification", "test_runner"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/deepseek-r1:32b --edit-format diff",
			"hermes":   "-p truenas -m deepseek-r1:32b",
			"opencode": "-m truenas/deepseek-r1:32b",
		},
		CommonPitfalls: []string{"Requires thinking token headroom; ensure diff generator omits <think> tokens."},
	},
	{
		ID:                "qwen3.8-uncensored:27b",
		VenueID:           "truenas",
		ProviderModelName: "qwen3.8-uncensored:27b",
		Tier:              "local",
		MaxContext:        32768,
		TokPerSecEst:      34.7,
		Uncensored:        true,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Dual-GPU balanced uncensored Qwen at a rapid 35 tok/s pace.\"",
		TaskFamilies:      []string{"red_team", "unfiltered_audit", "rapid_patching"},
		ToolDialect:       "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "sandbox_eval"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3.8-uncensored:27b --edit-format diff",
			"hermes":   "-p truenas -m qwen3.8-uncensored:27b",
			"opencode": "-m truenas/qwen3.8-uncensored:27b",
		},
		CommonPitfalls: []string{"32K context cap preserves dual-GPU allocation ceiling."},
	},
	{
		ID:                "llama3.3:70b",
		VenueID:           "truenas",
		ProviderModelName: "llama3.3:70b",
		Tier:              "local",
		MaxContext:        32768,
		TokPerSecEst:      11.5,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Flagship 70B parameter weight across both cards for high-adherence planning and policy formulation.\"",
		TaskFamilies:      []string{"flagship_general", "complex_planning", "policy_design"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"system_design", "governance"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/llama3.3:70b --edit-format diff",
			"hermes":   "-p truenas -m llama3.3:70b",
			"opencode": "-m truenas/llama3.3:70b",
		},
		CommonPitfalls: []string{"Larger footprint limits throughput to ~11.5 tok/s."},
	},
	{
		ID:                "qwen3.5:9b",
		VenueID:           "truenas",
		ProviderModelName: "qwen3.5:9b",
		Tier:              "local",
		MaxContext:        32768,
		TokPerSecEst:      88.5,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Sub-second lightning speed: 88 tok/s for rapid triage, single-file scripts, and instant lookups.\"",
		TaskFamilies:      []string{"subsecond_edit", "quick_lookup", "lightweight_triage"},
		ToolDialect:       "posix_shell",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "file_finder"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3.5:9b --edit-format diff",
			"hermes":   "-p truenas -m qwen3.5:9b",
			"opencode": "-m truenas/qwen3.5:9b",
		},
		CommonPitfalls: []string{"Not intended for deep multi-module refactoring."},
	},
	{
		ID:                 "qwen3.6:35b-a3b",
		VenueID:            "truenas",
		ProviderModelName:  "qwen3.6:35b-a3b",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       32.0,
		TaskFamilies:       []string{"code_refactor", "general_dev"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3.6:35b-a3b --edit-format diff",
			"opencode": "-m truenas/qwen3.6:35b-a3b",
		},
	},
	{
		ID:                 "qwen3-coder:30b",
		VenueID:            "truenas",
		ProviderModelName:  "qwen3-coder:30b",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       40.0,
		TaskFamilies:       []string{"code_refactor", "fast_coding"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "patch_verify"},
		HarnessFlags: map[string]string{
			"aider":    "--model ollama_chat/qwen3-coder:30b --edit-format diff",
			"opencode": "-m truenas/qwen3-coder:30b",
		},
	},
	{
		ID:                 "gemma4:31b",
		VenueID:            "truenas",
		ProviderModelName:  "gemma4:31b",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       28.0,
		TaskFamilies:       []string{"general_dev", "tool_orchestration"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git", "json_tools"},
		HarnessFlags: map[string]string{
			"opencode": "-m truenas/gemma4:31b",
		},
	},
	{
		ID:                 "mistral-small3.2:latest",
		VenueID:            "truenas",
		ProviderModelName:  "mistral-small3.2:latest",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       35.0,
		TaskFamilies:       []string{"general_dev", "tool_orchestration"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m truenas/mistral-small3.2:latest",
		},
	},
	{
		ID:                 "devstral-small-2:24b",
		VenueID:            "truenas",
		ProviderModelName:  "devstral-small-2:24b",
		Tier:               "local",
		MaxContext:         65536,
		TokPerSecEst:       38.0,
		TaskFamilies:       []string{"code_refactor", "fast_coding"},
		ToolDialect:        "posix_shell_and_unified_diff",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "patch_verify"},
		HarnessFlags: map[string]string{
			"opencode": "-m truenas/devstral-small-2:24b",
		},
	},
	{
		ID:                 "gpt-oss:20b",
		VenueID:            "truenas",
		ProviderModelName:  "gpt-oss:20b",
		Tier:               "local",
		MaxContext:         32768,
		TokPerSecEst:       45.0,
		TaskFamilies:       []string{"fast_coding", "lightweight_triage"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "cot_thinking_tags",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m truenas/gpt-oss:20b",
		},
	},
	{
		ID:                 "kv-ground-8b:latest",
		VenueID:            "truenas",
		ProviderModelName:  "kv-ground-8b:latest",
		Tier:               "local",
		MaxContext:         32768,
		TokPerSecEst:       75.0,
		TaskFamilies:       []string{"vision_inspection", "quick_lookup"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"image_diff"},
		HarnessFlags: map[string]string{
			"opencode": "-m truenas/kv-ground-8b:latest",
		},
	},

	// ==================== STRATA (BIGMAC MOE) ====================
	{
		ID:                "strata-inkling",
		VenueID:           "strata",
		ProviderModelName: "strata-inkling",
		Tier:              "local",
		MaxContext:        32768,
		TokPerSecEst:      25.0,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Thinking Machines Inkling-2-Mini with native DSpark Block-8 drafter and o200k byte BPE tokenizer.\"",
		TaskFamilies:      []string{"streaming_agent", "rapid_turnaround", "latent_moe"},
		ToolDialect:       "o200k_structured_xml",
		PreferredEditStyle: "diff",
		ThinkingMode:      "none",
		Skills:            []string{"streaming_eval"},
		HarnessFlags: map[string]string{
			"aider":    "--model openai/strata-inkling --edit-format diff",
			"hermes":   "-p strata -m strata-inkling",
			"opencode": "-m strata/strata-inkling",
		},
		CommonPitfalls: []string{"Thinking mode is strictly off (enforced by tokenizer)."},
	},

	// ==================== OPENROUTER (FREE TIER SPECIALS) ====================
	{
		ID:                "nemotron-3-nano-omni:free",
		VenueID:           "openrouter",
		ProviderModelName: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
		Tier:              "free",
		MaxContext:        65536,
		TokPerSecEst:      45.0,
		Uncensored:        false,
		SommelierSpecial:  true,
		SpecialPitch:      "\"And this evening on OpenRouter's complimentary menu: the NVIDIA Nemotron 3 Nano Omni 30B reasoning model — zero cost, high reasoning density!\"",
		TaskFamilies:      []string{"deep_reasoning", "free_cloud_compute", "code_refactor"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:      "cot_thinking_tags",
		Skills:            []string{"git", "test_runner"},
		HarnessFlags: map[string]string{
			"aider":    "--model openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free --edit-format diff",
			"hermes":   "-p openrouter -m nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
			"opencode": "-m openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
		},
		CommonPitfalls: []string{"Subject to provider rate-limiting during peak cloud hours."},
	},
	{
		ID:                "gemma-4-31b:free",
		VenueID:           "openrouter",
		ProviderModelName: "google/gemma-4-31b-it:free",
		Tier:              "free",
		MaxContext:        65536,
		TokPerSecEst:      35.0,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Google's dense Gemma-4 31B served complimentary via OpenRouter with 64K context.\"",
		TaskFamilies:      []string{"general_dev", "tool_orchestration", "free_cloud_compute"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:      "none",
		Skills:            []string{"git", "json_tools"},
		HarnessFlags: map[string]string{
			"aider":    "--model openrouter/google/gemma-4-31b-it:free --edit-format diff",
			"hermes":   "-p openrouter -m google/gemma-4-31b-it:free",
			"opencode": "-m openrouter/google/gemma-4-31b-it:free",
		},
		CommonPitfalls: []string{"Rate-limited if multiple agent sub-threads trigger simultaneously."},
	},
	{
		ID:                 "nemotron-3-ultra:free",
		VenueID:            "openrouter",
		ProviderModelName:  "nvidia/nemotron-3-ultra-550b-a55b:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       35.0,
		TaskFamilies:       []string{"deep_reasoning", "architecture_audit", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "cot_thinking_tags",
		Skills:             []string{"git", "system_design"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
		},
	},
	{
		ID:                 "nemotron-3.5-lightning:free",
		VenueID:            "openrouter",
		ProviderModelName:  "nvidia/nemotron-3.5-lightning:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       60.0,
		TaskFamilies:       []string{"fast_coding", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/nvidia/nemotron-3.5-lightning:free",
		},
	},
	{
		ID:                 "nemotron-3.5-super-vl:free",
		VenueID:            "openrouter",
		ProviderModelName:  "nvidia/nemotron-3.5-super-vl:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       40.0,
		TaskFamilies:       []string{"vision_inspection", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"image_diff"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/nvidia/nemotron-3.5-super-vl:free",
		},
	},
	{
		ID:                 "gemma-4-26b-a4b:free",
		VenueID:            "openrouter",
		ProviderModelName:  "google/gemma-4-26b-a4b-it:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       50.0,
		TaskFamilies:       []string{"general_dev", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/google/gemma-4-26b-a4b-it:free",
		},
	},
	{
		ID:                 "ernie-5.5-flash-preview:free",
		VenueID:            "openrouter",
		ProviderModelName:  "baidu/ernie-5.5-flash-preview:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       55.0,
		TaskFamilies:       []string{"general_dev", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/baidu/ernie-5.5-flash-preview:free",
		},
	},
	{
		ID:                 "ling-3.2-flash:free",
		VenueID:            "openrouter",
		ProviderModelName:  "inclusionai/ling-3.2-flash:free",
		Tier:               "free",
		MaxContext:         131072,
		TokPerSecEst:       55.0,
		TaskFamilies:       []string{"fast_coding", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/inclusionai/ling-3.2-flash:free",
		},
	},
	{
		ID:                 "lfm-3-1.7b:free",
		VenueID:            "openrouter",
		ProviderModelName:  "liquid/lfm-3-1.7b:free",
		Tier:               "free",
		MaxContext:         32768,
		TokPerSecEst:       95.0,
		TaskFamilies:       []string{"quick_lookup", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"file_finder"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/liquid/lfm-3-1.7b:free",
		},
	},
	{
		ID:                 "particle-1:free",
		VenueID:            "openrouter",
		ProviderModelName:  "particle-ai/particle-1:free",
		Tier:               "free",
		MaxContext:         65536,
		TokPerSecEst:       45.0,
		TaskFamilies:       []string{"general_dev", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/particle-ai/particle-1:free",
		},
	},
	{
		ID:                 "flint-v1.0:free",
		VenueID:            "openrouter",
		ProviderModelName:  "recursive/flint-v1.0:free",
		Tier:               "free",
		MaxContext:         65536,
		TokPerSecEst:       45.0,
		TaskFamilies:       []string{"general_dev", "free_cloud_compute"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "none",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/recursive/flint-v1.0:free",
		},
	},

	// ==================== OPENROUTER (BYOK / METERED) ====================
	{
		ID:                 "openrouter-deepseek-v4.1-flash-byok",
		VenueID:            "openrouter-byok",
		ProviderModelName:  "deepseek/deepseek-v4.1-flash",
		Tier:               "commercial_api",
		MaxContext:         131072,
		CostPer1MInput:     0.14,
		TokPerSecEst:       65.0,
		TaskFamilies:       []string{"code_refactor", "general_dev", "cost_efficient_cloud"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "off",
		Skills:             []string{"git", "ast_search"},
		HarnessFlags: map[string]string{
			"aider":    "--model openrouter/deepseek/deepseek-v4.1-flash --edit-format diff",
			"opencode": "-m openrouter/deepseek/deepseek-v4.1-flash",
		},
	},
	{
		ID:                 "openrouter-gpt-oss-20b-byok",
		VenueID:            "openrouter-byok",
		ProviderModelName:  "openai/gpt-oss-20b",
		Tier:               "commercial_api",
		MaxContext:         131072,
		TokPerSecEst:       80.0,
		TaskFamilies:       []string{"fast_coding", "cost_efficient_cloud"},
		ToolDialect:        "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:       "cot_thinking_tags",
		Skills:             []string{"git"},
		HarnessFlags: map[string]string{
			"opencode": "-m openrouter/openai/gpt-oss-20b",
		},
	},

	// ==================== SUBSCRIPTION & COMMERCIAL API ====================
	{
		ID:                "gemini-3.5-flash",
		VenueID:           "gemini",
		ProviderModelName: "google/gemini-3.5-flash",
		Tier:              "subscription",
		MaxContext:        1048576,
		TokPerSecEst:      95.0,
		Uncensored:        false,
		SommelierSpecial:  true,
		SpecialPitch:      "\"From Google AI Studio: Gemini 3.5 Flash boasting a 1,000,000 token context window and 95 tok/s generation for macro architecture ingestion.\"",
		TaskFamilies:      []string{"macro_architecture_audit", "whole_monorepo_analysis", "massive_context"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "monorepo_indexer"},
		HarnessFlags: map[string]string{
			"aider":    "--model openrouter/google/gemini-3.5-flash --edit-format diff",
			"hermes":   "-p openrouter -m google/gemini-3.5-flash",
			"opencode": "-m openrouter/google/gemini-3.5-flash",
		},
		CommonPitfalls: []string{"Requires network egress; do not route sovereign-isolated air-gapped tasks here."},
	},
	{
		ID:                "deepseek-chat",
		VenueID:           "deepseek",
		ProviderModelName: "deepseek/deepseek-chat",
		Tier:              "commercial_api",
		MaxContext:        131072,
		TokPerSecEst:      55.0,
		Uncensored:        false,
		SommelierSpecial:  false,
		SpecialPitch:      "\"Commercial DeepSeek V3 direct: ultra-low cost ($0.14/1M) with high coding and reasoning benchmark scores.\"",
		TaskFamilies:      []string{"code_refactor", "general_dev", "cost_efficient_cloud"},
		ToolDialect:       "openai_strict_json",
		PreferredEditStyle: "diff",
		ThinkingMode:      "off",
		Skills:            []string{"git", "ast_search"},
		HarnessFlags: map[string]string{
			"aider":    "--model openrouter/deepseek/deepseek-chat --edit-format diff",
			"hermes":   "-p openrouter -m deepseek/deepseek-chat",
			"opencode": "-m openrouter/deepseek/deepseek-chat",
		},
		CommonPitfalls: []string{"Cloud API subject to standard latency jitter."},
	},
}

func checkEndpointHealth(url string, timeout time.Duration) bool {
	if url == "" {
		return true // Assumed reachable if no specific health probe URL
	}
	client := http.Client{Timeout: timeout}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}

func checkVenueHealth(v ServerVenue) bool {
	if v.HealthCheckURL == "" {
		return true
	}
	return checkEndpointHealth(v.HealthCheckURL, 2*time.Second)
}

func recommendModels(req RecommendRequest) []Recommendation {
	if req.MaxResults <= 0 {
		req.MaxResults = 3
	}

	// Step 1: Probe venue readiness if venue is local
	venueStatus := make(map[string]bool)
	for id, v := range Venues {
		if v.Type == "local_sovereign" {
			venueStatus[id] = checkVenueHealth(v)
		} else {
			venueStatus[id] = true // Assume cloud venues ready unless explicitly excluded
		}
	}

	// Step 2: Filter candidates
	type scoredCandidate struct {
		model ModelProfile
		venue ServerVenue
		score int
	}
	var candidates []scoredCandidate

	for _, m := range Catalog {
		v, exists := Venues[m.VenueID]
		if !exists {
			continue
		}
		// Check venue alive status
		if isAlive, ok := venueStatus[m.VenueID]; ok && !isAlive {
			continue // Venue is currently down
		}
		// Sovereignty filter
		if req.OnlySovereignLocal && v.Type != "local_sovereign" {
			continue
		}
		// Venue whitelist filter
		if len(req.AllowedVenues) > 0 {
			allowed := false
			for _, av := range req.AllowedVenues {
				if strings.EqualFold(av, m.VenueID) {
					allowed = true
					break
				}
			}
			if !allowed {
				continue
			}
		}
		// Uncensored constraint
		if req.RequiresUncensored && !m.Uncensored {
			continue
		}
		// Context capacity constraint
		if req.EstimatedContextTokens > 0 && m.MaxContext < req.EstimatedContextTokens {
			continue
		}

		// Calculate fit score
		score := 0
		// Task family match
		for _, fam := range m.TaskFamilies {
			if strings.EqualFold(fam, req.TaskFamily) {
				score += 100
			}
		}
		// Specials boost
		if m.SommelierSpecial {
			score += 35
		}
		// Local preference over cloud for sovereign workloads
		if v.Type == "local_sovereign" {
			score += 20
		}
		// Free tier bonus
		if m.Tier == "free" {
			score += 15
		}
		// Big context match
		if req.EstimatedContextTokens > 65536 && m.MaxContext >= 262144 {
			score += 40
		}
		// High throughput match
		if m.TokPerSecEst > 35.0 {
			score += 10
		}

		candidates = append(candidates, scoredCandidate{
			model: m,
			venue: v,
			score: score,
		})
	}

	// Sort by score descending
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].score > candidates[j].score
	})

	var results []Recommendation
	for i, c := range candidates {
		if i >= req.MaxResults {
			break
		}
		rationale := fmt.Sprintf("Rank #%d: %s on %s matches '%s' with %d max context at ~%.1f tok/s.",
			i+1, c.model.ID, c.venue.Name, req.TaskFamily, c.model.MaxContext, c.model.TokPerSecEst)

		results = append(results, Recommendation{
			Rank:              i + 1,
			ModelID:           c.model.ID,
			VenueID:           c.model.VenueID,
			VenueName:         c.venue.Name,
			Endpoint:          c.venue.Endpoint,
			ProviderModel:     c.model.ProviderModelName,
			AvailableContext:  c.model.MaxContext,
			CostTier:          c.model.Tier,
			TokPerSec:         c.model.TokPerSecEst,
			IsSpecial:         c.model.SommelierSpecial,
			WaiterPitch:       c.model.SpecialPitch,
			ToolDialect:       c.model.ToolDialect,
			ThinkingMode:      c.model.ThinkingMode,
			RecommendedSkills: c.model.Skills,
			HarnessFlags:      c.model.HarnessFlags,
			Rationale:         rationale,
		})
	}

	return results
}

func getCatalogByVenue(venueID string) (ServerVenue, []ModelProfile, bool) {
	v, exists := Venues[venueID]
	if !exists {
		return ServerVenue{}, nil, false
	}
	var models []ModelProfile
	for _, m := range Catalog {
		if m.VenueID == venueID {
			models = append(models, m)
		}
	}
	return v, models, true
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
					"version": "2.0.0",
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
						"name":        "recommend_models",
						"description": "Returns a prioritized menu of model recommendations across all venues (local, cloud, free-tier specials) matching the task family, context demand, and censorship constraints.",
						"inputSchema": map[string]interface{}{
							"type": "object",
							"properties": map[string]interface{}{
								"task_family": map[string]interface{}{
									"type":        "string",
									"description": "Task classification (e.g. 'code_refactor', 'large_repo_ingest', 'red_team', 'deep_reasoning', 'subsecond_edit').",
								},
								"estimated_context_tokens": map[string]interface{}{
									"type":        "integer",
									"description": "Estimated total context tokens needed (up to 1,000,000).",
								},
								"requires_uncensored": map[string]interface{}{
									"type":        "boolean",
									"description": "True if the task requires abliterated/uncensored weights without safety refusal triggers.",
								},
								"only_sovereign_local": map[string]interface{}{
									"type":        "boolean",
									"description": "True to restrict recommendations strictly to local sovereign hardware (BigMac / TrueNAS).",
								},
								"allowed_venues": map[string]interface{}{
									"type":        "array",
									"items":       map[string]string{"type": "string"},
									"description": "Optional filter to allow only specific venues: ['bigmac', 'truenas', 'strata', 'openrouter', 'gemini', 'deepseek'].",
								},
								"max_results": map[string]interface{}{
									"type":        "integer",
									"description": "Number of ranked options to return (default: 3).",
								},
							},
							"required": []string{"task_family"},
						},
					},
					{
						"name":        "get_venue_catalog",
						"description": "Returns the model catalog and live operational readiness for a specific server venue (e.g. 'bigmac', 'truenas', 'openrouter', 'gemini').",
						"inputSchema": map[string]interface{}{
							"type": "object",
							"properties": map[string]interface{}{
								"venue_id": map[string]interface{}{
									"type":        "string",
									"description": "Venue identifier: 'bigmac', 'truenas', 'strata', 'openrouter', 'gemini', 'deepseek'.",
								},
							},
							"required": []string{"venue_id"},
						},
					},
					{
						"name":        "get_sommelier_specials",
						"description": "Lists the featured 'Chef's Specials' across local hardware and cloud free tiers (highlighted recommendations with their waiter pitches).",
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
			case "recommend_models":
				var recReq RecommendRequest
				if err := json.Unmarshal(callParams.Arguments, &recReq); err != nil {
					resp.Error = &RPCError{Code: -32602, Message: err.Error()}
					break
				}
				recs := recommendModels(recReq)
				outText, _ := json.MarshalIndent(recs, "", "  ")
				resp.Result = map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": string(outText)}},
				}
			case "get_venue_catalog":
				var vReq struct {
					VenueID string `json:"venue_id"`
				}
				if err := json.Unmarshal(callParams.Arguments, &vReq); err != nil {
					resp.Error = &RPCError{Code: -32602, Message: err.Error()}
					break
				}
				venue, models, ok := getCatalogByVenue(vReq.VenueID)
				if !ok {
					resp.Error = &RPCError{Code: -32602, Message: fmt.Sprintf("Unknown venue ID: '%s'", vReq.VenueID)}
					break
				}
				isAlive := checkVenueHealth(venue)
				res := map[string]interface{}{
					"venue":       venue,
					"is_alive":    isAlive,
					"model_count": len(models),
					"models":      models,
				}
				outText, _ := json.MarshalIndent(res, "", "  ")
				resp.Result = map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": string(outText)}},
				}
			case "get_sommelier_specials":
				var specials []ModelProfile
				for _, m := range Catalog {
					if m.SommelierSpecial {
						specials = append(specials, m)
					}
				}
				outText, _ := json.MarshalIndent(specials, "", "  ")
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
	recommendMode := flag.String("recommend", "", "Recommend model menu for task family (e.g. code_refactor, deep_reasoning)")
	venueFlag := flag.String("venue", "", "Query catalog for a specific venue (bigmac, truenas, strata, openrouter, gemini, deepseek)")
	contextTokens := flag.Int("context", 0, "Estimated context token demand")
	uncensored := flag.Bool("uncensored", false, "Require uncensored/abliterated weights")
	sovereignOnly := flag.Bool("sovereign", false, "Enforce strict local sovereign hardware only")
	specialsOnly := flag.Bool("specials", false, "Show this evening's featured chef/sommelier specials")
	flag.Parse()

	if *mcpMode {
		handleMCP(os.Stdin, os.Stdout)
		return
	}

	if *specialsOnly {
		fmt.Printf("=============================================================================\n")
		fmt.Printf("   MODEL COMPASS — THIS EVENING'S SOMMELIER SPECIALS & CHEF'S RECOMMENDATIONS \n")
		fmt.Printf("=============================================================================\n\n")
		for _, m := range Catalog {
			if m.SommelierSpecial {
				v := Venues[m.VenueID]
				fmt.Printf("★ [%s] %s (%s, %d context, ~%.1f tok/s)\n", v.Name, m.ID, m.Tier, m.MaxContext, m.TokPerSecEst)
				fmt.Printf("  %s\n\n", m.SpecialPitch)
			}
		}
		return
	}

	if *venueFlag != "" {
		venue, models, ok := getCatalogByVenue(*venueFlag)
		if !ok {
			fmt.Printf("Error: Unknown venue '%s'. Available: bigmac, truenas, strata, openrouter, gemini, deepseek\n", *venueFlag)
			os.Exit(1)
		}
		isAlive := checkVenueHealth(venue)
		fmt.Printf("Venue: %s (%s)\n", venue.Name, venue.Type)
		fmt.Printf("Endpoint: %s | Active/Alive: %t\n", venue.Endpoint, isAlive)
		fmt.Printf("Description: %s\n\n", venue.Description)
		fmt.Printf("Models (%d):\n", len(models))
		for _, m := range models {
			fmt.Printf("• %-26s | Ctx: %7d | Tok/s: %4.1f | Tier: %-12s | Dialect: %s\n",
				m.ID, m.MaxContext, m.TokPerSecEst, m.Tier, m.ToolDialect)
		}
		return
	}

	if *recommendMode != "" {
		recs := recommendModels(RecommendRequest{
			TaskFamily:             *recommendMode,
			EstimatedContextTokens: *contextTokens,
			RequiresUncensored:     *uncensored,
			OnlySovereignLocal:     *sovereignOnly,
			MaxResults:             3,
		})
		out, _ := json.MarshalIndent(recs, "", "  ")
		fmt.Println(string(out))
		return
	}

	// Default CLI output: display venue breakdown and summary
	fmt.Printf("=============================================================================\n")
	fmt.Printf(" Model Compass Multi-Venue Sovereign & Cloud Router (v2.0.0)\n")
	fmt.Printf("=============================================================================\n\n")
	fmt.Printf("Configured Venues (%d):\n", len(Venues))
	for id, v := range Venues {
		alive := checkVenueHealth(v)
		fmt.Printf("  [%-10s] %-36s | Type: %-15s | Ready: %t\n", id, v.Name, v.Type, alive)
	}
	fmt.Printf("\nTotal Models across all menus: %d\n\n", len(Catalog))
	fmt.Printf("CLI Usage:\n")
	fmt.Printf("  model-compass -specials\n")
	fmt.Printf("  model-compass -venue <venue_id>   (bigmac, truenas, openrouter, gemini, deepseek)\n")
	fmt.Printf("  model-compass -recommend <task> [-context <tokens>] [-uncensored] [-sovereign]\n")
	fmt.Printf("  model-compass -mcp (JSON-RPC 2.0 stdio)\n")
}
