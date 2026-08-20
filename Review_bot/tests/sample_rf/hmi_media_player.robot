*** Settings ***
Documentation    HMI Media Player Touchscreen Validation Test Suite
Library          AppiumLibrary

*** Variables ***
${HMI_APP}       com.automotive.hmi.mediaplayer
${PLAY_BUTTON}   id=com.automotive.hmi:id/play_btn

*** Test Cases ***
Verify Touchscreen Play Pause Interaction
    [Documentation]    Validates media playback toggling on HMI screen
    [Tags]             HMI    Media    Sanity
    Open HMI Media Player
    Click Element      ${PLAY_BUTTON}
    # Anti-pattern: Hardcoded sleep
    Sleep    3s
    # Anti-pattern: Fragile index XPath
    Element Should Be Visible    xpath=//div[2]/div[1]/span[3]

*** Keywords ***
Open HMI Media Player
    Log    Launching HMI Media Player App
