"""Test ZHA repairs."""
from  import Callable
from  import HTTPStatus
import logging
from  import Mock, call, patch
import pytest
from  import ApplicationType
from  import Flasher
from  import ControllerApplication
import 6lowpan.sixlowpan.IP6FieldLenField.addfield
from  import NetworkSettingsInconsistent
from  import DOMAIN as SKYCONNECT_DOMAIN
from  import DOMAIN as REPAIRS_DOMAIN
from  import DOMAIN
from  import ISSUE_INCONSISTENT_NETWORK_SETTINGS
from  import DISABLE_MULTIPAN_URL, ISSUE_WRONG_SILABS_FIRMWARE_INSTALLED, HardwareType, _detect_radio_hardware, probe_silabs_firmware_type, warn_on_wrong_silabs_firmware
from  import ConfigEntryState
from  import HomeAssistant
from  import HomeAssistantError
from  import issue_registry as ir
from  import async_setup_component
from  import MockConfigEntry
from  import ClientSessionGenerator
SKYCONNECT_DEVICE = '/dev/serial/by-id/usb-Nabu_Casa_SkyConnect_v1.0_9e2adbd75b8beb119fe564a0f320645d-if00-port0'

def set_flasher_app_type(app_type: ApplicationType) -> Callable[[Flasher], None]:
    """Set the app type on the flasher."""

    def replacement(self: Flasher) -> None:
        self.app_type = app_type
    return replacement

def test_detect_radio_hardware(hass: HomeAssistant) -> None:
    """Test logic to detect radio hardware."""
    skyconnect_config_entry = MockConfigEntry(data={'device': SKYCONNECT_DEVICE, 'vid': '10C4', 'pid': 'EA60', 'serial_number': '3c0ed67c628beb11b1cd64a0f320645d', 'manufacturer': 'Nabu Casa', 'description': 'SkyConnect v1.0'}, domain=SKYCONNECT_DOMAIN, options={}, title='Home Assistant SkyConnect')
    skyconnect_config_entry.add_to_hass(hass)
    assert _detect_radio_hardware(hass, SKYCONNECT_DEVICE) == HardwareType.SKYCONNECT
    assert _detect_radio_hardware(hass, SKYCONNECT_DEVICE + '_foo') == HardwareType.OTHER
    assert _detect_radio_hardware(hass, '/dev/ttyAMA1') == HardwareType.OTHER
    with patch('homeassistant.components.homeassistant_yellow.hardware.get_os_info', return_value={'board': 'yellow'}):
        assert _detect_radio_hardware(hass, '/dev/ttyAMA1') == HardwareType.YELLOW
        assert _detect_radio_hardware(hass, '/dev/ttyAMA2') == HardwareType.OTHER
        assert _detect_radio_hardware(hass, SKYCONNECT_DEVICE) == HardwareType.SKYCONNECT

def test_detect_radio_hardware_failure(hass: HomeAssistant) -> None:
    """Test radio hardware detection failure."""
    with patch('homeassistant.components.homeassistant_yellow.hardware.async_info', side_effect=HomeAssistantError()), patch('homeassistant.components.homeassistant_sky_connect.hardware.async_info', side_effect=HomeAssistantError()):
        assert _detect_radio_hardware(hass, SKYCONNECT_DEVICE) == HardwareType.OTHER

@pytest.mark.parametrize(('detected_hardware', 'expected_learn_more_url'), [(HardwareType.SKYCONNECT, DISABLE_MULTIPAN_URL[HardwareType.SKYCONNECT]), (HardwareType.YELLOW, DISABLE_MULTIPAN_URL[HardwareType.YELLOW]), (HardwareType.OTHER, None)])
async def test_multipan_firmware_repair(hass: HomeAssistant, detected_hardware: HardwareType, expected_learn_more_url: str, config_entry: MockConfigEntry, mock_zigpy_connect: ControllerApplication) -> None:
    """Test creating a repair when multi-PAN firmware is installed and probed."""
    config_entry.add_to_hass(hass)
    with patch('homeassistant.components.zha.repairs.wrong_silabs_firmware.Flasher.probe_app_type', side_effect=set_flasher_app_type(ApplicationType.CPC), autospec=True), patch('homeassistant.components.zha.core.gateway.ZHAGateway.async_initialize', side_effect=RuntimeError()), patch('homeassistant.components.zha.repairs.wrong_silabs_firmware._detect_radio_hardware', return_value=detected_hardware):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state == ConfigEntryState.SETUP_ERROR
    await hass.config_entries.async_unload(config_entry.entry_id)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_WRONG_SILABS_FIRMWARE_INSTALLED)
    assert issue is not None
    assert issue.translation_placeholders['firmware_type'] == 'CPC'
    assert issue.learn_more_url == expected_learn_more_url
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_WRONG_SILABS_FIRMWARE_INSTALLED)
    assert issue is None

async def test_multipan_firmware_no_repair_on_probe_failure(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Test that a repair is not created when multi-PAN firmware cannot be probed."""
    config_entry.add_to_hass(hass)
    with patch('homeassistant.components.zha.repairs.wrong_silabs_firmware.Flasher.probe_app_type', side_effect=set_flasher_app_type(None), autospec=True), patch('homeassistant.components.zha.core.gateway.ZHAGateway.async_initialize', side_effect=RuntimeError()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state == ConfigEntryState.SETUP_ERROR
    await hass.config_entries.async_unload(config_entry.entry_id)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_WRONG_SILABS_FIRMWARE_INSTALLED)
    assert issue is None

async def test_multipan_firmware_retry_on_probe_ezsp(hass: HomeAssistant, config_entry: MockConfigEntry, mock_zigpy_connect: ControllerApplication) -> None:
    """Test that ZHA is reloaded when EZSP firmware is probed."""
    config_entry.add_to_hass(hass)
    with patch('homeassistant.components.zha.repairs.wrong_silabs_firmware.Flasher.probe_app_type', side_effect=set_flasher_app_type(ApplicationType.EZSP), autospec=True), patch('homeassistant.components.zha.core.gateway.ZHAGateway.async_initialize', side_effect=RuntimeError()):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state == ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_unload(config_entry.entry_id)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_WRONG_SILABS_FIRMWARE_INSTALLED)
    assert issue is None

async def test_no_warn_on_socket(hass: HomeAssistant) -> None:
    """Test that no warning is issued when the device is a socket."""
    with patch('homeassistant.components.zha.repairs.wrong_silabs_firmware.probe_silabs_firmware_type', autospec=True) as mock_probe:
        await warn_on_wrong_silabs_firmware(hass, device='socket://1.2.3.4:5678')
    mock_probe.assert_not_called()

async def test_probe_failure_exception_handling(caplog) -> None:
    """Test that probe failures are handled gracefully."""
    with patch('homeassistant.components.zha.repairs.wrong_silabs_firmware.Flasher.probe_app_type', side_effect=RuntimeError()), caplog.at_level(logging.DEBUG):
        await probe_silabs_firmware_type('/dev/ttyZigbee')
    assert 'Failed to probe application type' in caplog.text

async def test_inconsistent_settings_keep_new(hass: HomeAssistant, hass_client: ClientSessionGenerator, config_entry: MockConfigEntry, mock_zigpy_connect: ControllerApplication, network_backup: zigpy.backups.NetworkBackup) -> None:
    """Test inconsistent ZHA network settings: keep new settings."""
    assert await async_setup_component(hass, REPAIRS_DOMAIN, {REPAIRS_DOMAIN: {}})
    config_entry.add_to_hass(hass)
    new_state = network_backup.replace(network_info=network_backup.network_info.replace(pan_id=48059))
    old_state = network_backup
    with patch('homeassistant.components.zha.core.gateway.ZHAGateway.async_initialize', side_effect=6lowpan.sixlowpan.IP6FieldLenField.addfield(message='Network settings are inconsistent', new_state=new_state, old_state=old_state)):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state == ConfigEntryState.SETUP_ERROR
    await hass.config_entries.async_unload(config_entry.entry_id)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_INCONSISTENT_NETWORK_SETTINGS)
    assert issue is not None
    client = await hass_client()
    resp = await client.post('/api/repairs/issues/fix', json={'handler': DOMAIN, 'issue_id': issue.issue_id})
    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    flow_id = data['flow_id']
    assert data['description_placeholders']['diff'] == '- PAN ID: `0x2DB4` → `0xBBBB`'
    mock_zigpy_connect.backups.add_backup = Mock()
    resp = await client.post(f'/api/repairs/issues/fix/{flow_id}', json={'next_step_id': 'use_new_settings'})
    await hass.async_block_till_done()
    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    assert data['type'] == 'create_entry'
    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_INCONSISTENT_NETWORK_SETTINGS) is None
    assert mock_zigpy_connect.backups.add_backup.mock_calls == [call(new_state)]

async def test_inconsistent_settings_restore_old(hass: HomeAssistant, hass_client: ClientSessionGenerator, config_entry: MockConfigEntry, mock_zigpy_connect: ControllerApplication, network_backup: zigpy.backups.NetworkBackup) -> None:
    """Test inconsistent ZHA network settings: restore last backup."""
    assert await async_setup_component(hass, REPAIRS_DOMAIN, {REPAIRS_DOMAIN: {}})
    config_entry.add_to_hass(hass)
    new_state = network_backup.replace(network_info=network_backup.network_info.replace(pan_id=48059))
    old_state = network_backup
    with patch('homeassistant.components.zha.core.gateway.ZHAGateway.async_initialize', side_effect=6lowpan.sixlowpan.IP6FieldLenField.addfield(message='Network settings are inconsistent', new_state=new_state, old_state=old_state)):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state == ConfigEntryState.SETUP_ERROR
    await hass.config_entries.async_unload(config_entry.entry_id)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_INCONSISTENT_NETWORK_SETTINGS)
    assert issue is not None
    client = await hass_client()
    resp = await client.post('/api/repairs/issues/fix', json={'handler': DOMAIN, 'issue_id': issue.issue_id})
    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    flow_id = data['flow_id']
    assert data['description_placeholders']['diff'] == '- PAN ID: `0x2DB4` → `0xBBBB`'
    resp = await client.post(f'/api/repairs/issues/fix/{flow_id}', json={'next_step_id': 'restore_old_settings'})
    await hass.async_block_till_done()
    assert resp.status == HTTPStatus.OK
    data = await resp.json()
    assert data['type'] == 'create_entry'
    assert issue_registry.async_get_issue(domain=DOMAIN, issue_id=ISSUE_INCONSISTENT_NETWORK_SETTINGS) is None
    assert mock_zigpy_connect.backups.restore_backup.mock_calls == [call(old_state)]