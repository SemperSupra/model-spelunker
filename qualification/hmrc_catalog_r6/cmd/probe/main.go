// Public synthetic provenance receipt; no private catalog, GitHub credentials,
// model inference, or promotion into an authoritative owner DLE.
package main
import(
 "context"
 "encoding/json"
 "fmt"
 "os"
 "time"

 catalog "example.com/sempersupra/hmrc-public-catalog-r6"
)
func main(){
 ctx,cancel:=context.WithTimeout(context.Background(),20*time.Second)
 defer cancel()
 receipt,err:=catalog.FetchPinned(ctx,nil,catalog.PublicPin())
 if err!=nil{fmt.Fprintln(os.Stderr,err);os.Exit(2)}
 if err:=json.NewEncoder(os.Stdout).Encode(receipt);err!=nil{
  fmt.Fprintln(os.Stderr,err);os.Exit(3)
 }
}
