#!/usr/bin/env python3
from qualification.validate_tts_audio import word_error_count, words

expected=words("The blue lantern is beside the red bridge. The count is seven.")
assert word_error_count(expected,expected)==0
one=expected.copy()
one[1]="green"
assert word_error_count(expected,one)==1
missing=expected[:-1]
assert word_error_count(expected,missing)==1
assert words("Seven, BRIDGE!") == ["seven","bridge"]
print("PASS TTS validator metric self-test")
