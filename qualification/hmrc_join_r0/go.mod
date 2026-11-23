module example.com/sempersupra/hmrc-join-r0

go 1.23.0

require (
    example.com/sempersupra/hmrc-r0 v0.0.0
    example.com/sempersupra/hmrc-telemetry-r0 v0.0.0
)

replace example.com/sempersupra/hmrc-r0 => ../hmrc_r0
replace example.com/sempersupra/hmrc-telemetry-r0 => ../hmrc_telemetry_r0
