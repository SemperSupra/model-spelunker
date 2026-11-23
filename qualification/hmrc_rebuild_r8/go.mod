module example.com/sempersupra/hmrc-rebuild-r8

go 1.23.0

require (
  example.com/sempersupra/hmrc-r0 v0.0.0
  example.com/sempersupra/hmrc-evidence-r2 v0.0.0
  example.com/sempersupra/hmrc-intent-r7 v0.0.0
)
replace example.com/sempersupra/hmrc-r0 => ../hmrc_r0
replace example.com/sempersupra/hmrc-evidence-r2 => ../hmrc_evidence_r2
replace example.com/sempersupra/hmrc-intent-r7 => ../hmrc_intent_r7
