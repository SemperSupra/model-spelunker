package main

import (
  "bytes"
  "encoding/json"
  "strings"
  "testing"
)

type rpcResult struct {
  JSONRPC string `json:"jsonrpc"`
  ID json.RawMessage `json:"id"`
  Error *RPCError `json:"error"`
  Result json.RawMessage `json:"result"`
}
func runFixture(s string) []rpcResult {
  var out bytes.Buffer
  handleMCP(strings.NewReader(s), &out)
  var all []rpcResult
  for _,line:=range strings.Split(strings.TrimSpace(out.String()),"\n") {
    if line==""{continue}
    var r rpcResult
    if err:=json.Unmarshal([]byte(line),&r);err!=nil {
      all=append(all,rpcResult{JSONRPC:"DECODE_ERROR"})
      continue
    }
    all=append(all,r)
  }
  return all
}
func TestMCPStandaloneInitializationAndCatalog(t *testing.T) {
  results:=runFixture("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\"}\n{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\"}\n")
  if len(results)!=2{t.Fatalf("expected 2 responses, got %d",len(results))}
  for i,r:=range results {
    if r.JSONRPC!="2.0"||r.Error!=nil||string(r.ID)!=string([]string{"1","2"}[i])||len(r.Result)==0{
      t.Fatalf("bad JSON-RPC response: %+v",r)
    }
  }
  if !bytes.Contains(results[1].Result,[]byte("recommend_models")) {t.Fatal("existing tool interface lost")}
}
func TestMCPMalformedJSONReturnsParseError(t *testing.T) {
  result:=runFixture("{not-json}\n")
  if len(result)!=1||result[0].Error==nil||result[0].Error.Code!=-32700{
    t.Fatalf("malformed JSON silently dropped: %+v",result)
  }
}
func TestMCPInvalidProtocolFailsClosed(t *testing.T) {
  result:=runFixture("{\"jsonrpc\":\"1.0\",\"id\":5,\"method\":\"initialize\"}\n")
  if len(result)!=1||result[0].Error==nil||result[0].Error.Code!=-32600{
    t.Fatalf("wrong protocol version accepted: %+v",result)
  }
}
func TestMCPNotificationNeverReceivesResponse(t *testing.T) {
  result:=runFixture("{\"jsonrpc\":\"2.0\",\"method\":\"other/notification\"}\n")
  if len(result)!=0{t.Fatalf("notification improperly receives RPC response: %+v",result)}
}
func TestMCPLargeValidLineDoesNotSilentlyDisappear(t *testing.T) {
  input:=map[string]interface{}{"jsonrpc":"2.0","id":7,"method":"ping","padding":strings.Repeat("a",75*1024)}
  blob,err:=json.Marshal(input);if err!=nil{t.Fatal(err)}
  result:=runFixture(string(blob)+"\n")
  if len(result)!=1||result[0].Error!=nil||string(result[0].ID)!="7" {
    t.Fatalf("large but bounded request was lost: %+v",result)
  }
}
func TestMCPTooLargeLineHasBoundedError(t *testing.T) {
  input:=map[string]interface{}{"jsonrpc":"2.0","id":9,"method":"ping","padding":strings.Repeat("a",2<<20)}
  blob,err:=json.Marshal(input);if err!=nil{t.Fatal(err)}
  result:=runFixture(string(blob)+"\n")
  if len(result)!=1||result[0].Error==nil{
    t.Fatalf("oversized request silently dropped: %+v",result)
  }
}
func TestMCPUnknownMethodIsNotFabricatedSuccess(t *testing.T){
  result:=runFixture("{\"jsonrpc\":\"2.0\",\"id\":12,\"method\":\"unrecognized_method\"}\n")
  if len(result)!=1||result[0].Error==nil||result[0].Error.Code!=-32601{t.Fatalf("unsupported method: %+v",result)}
}
