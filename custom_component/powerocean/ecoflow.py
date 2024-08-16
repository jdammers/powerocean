"""ecoflow.py: API for PowerOcean integration."""
import requests
import base64
from collections import namedtuple
from requests.exceptions import RequestException

from homeassistant.exceptions import IntegrationError
from homeassistant.util.json import json_loads

from .const import _LOGGER, ISSUE_URL_ERROR_MESSAGE


# Better storage of PowerOcean endpoint
PowerOceanEndPoint = namedtuple(
    "PowerOceanEndPoint",
    "internal_unique_id, serial, name, friendly_name, value, unit, description",
)


# ecoflow_api to detect device and get device info, fetch the actual data from the PowerOcean device, and parse it
class EcoflowApi:
    def __init__(self, serialnumber, username, password):
        self.sn = serialnumber
        self.session = requests.Session()
        self.device = None
        self.url_iot_app = "https://api.ecoflow.com/auth/login"
        self.url_iot_mqtt = "https://api.ecoflow.com/iot-auth/app/certification"
        self.url_user_fetch = f"https://api-e.ecoflow.com/provider-service/user/device/detail?sn={self.sn}"

        # MQTT Certs
        self.ecoflow_username = username
        self.ecoflow_password = password
        self.user_id = None
        self.token = None
        self.mqtt_url = "mqtt.mqtt.com"
        self.mqtt_port = 8883
        self.mqtt_username = None
        self.mqtt_password = None

        self.unique_id = serialnumber



    def authorize(self):
        auth_OK = False  # default
        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {
            "email": self.ecoflow_username,
            "password": base64.b64encode(self.ecoflow_password.encode()).decode(),
            "scene": "IOT_APP",
            "userType": "ECOFLOW"
        }

        try:
            url = self.url_iot_app
            _LOGGER.info(f"Login to EcoFlow API {url}")
            request = requests.post(url, json=data, headers=headers)
            response = self.get_json_response(request)

        except ConnectionError:
            error = f"Unable to connect to {self.url_iot_app}. Device might be offline."
            _LOGGER.warning( error + ISSUE_URL_ERROR_MESSAGE )
            raise IntegrationError(error)

        try:
            self.token = response["data"]["token"]
            self.user_id = response["data"]["user"]["userId"]
            user_name = response["data"]["user"].get("name", "<no user name>")
            auth_OK = True

        except KeyError as key:
            raise Exception(f"Failed to extract key {key} from response: {response}")

        _LOGGER.info(f"Successfully logged in: {user_name}")

        # MQTT CERT
        headers = {"lang": "en_US", "authorization": f"Bearer {self.token}"}
        data = {"userId": self.user_id}

        url = self.url_iot_mqtt
        _LOGGER.info(f"Requesting IoT MQTT credentials {url}")
        request = requests.get(url, data=data, headers=headers)
        response = self.get_json_response(request)

        try:
            self.mqtt_url = response["data"]["url"]
            self.mqtt_port = int(response["data"]["port"])
            self.mqtt_username = response["data"]["certificateAccount"]
            self.mqtt_password = response["data"]["certificatePassword"]

        except KeyError as key:
            raise Exception(f"Failed to extract key {key} from {response}")

        _LOGGER.info(f"Successfully extracted account: {self.mqtt_username}")

        return auth_OK


    def get_device(self):
        self.device = {
            "product": "PowerOcean",
            "vendor": "Ecoflow",
            "serial": self.sn,
            "version": "5.1.15",
            "build": "13",
            "name": "PowerOcean",
            "features": "Photovoltaik"
        }

        return self.device

    def get_json_response(self, request):
        if request.status_code != 200:
            raise Exception(f"Got HTTP status code {request.status_code}: {request.text}")
        try:
            response = json_loads(request.text)
            response_message = response["message"]
        except KeyError as key:
            raise Exception(f"Failed to extract key {key} from {json_loads(request.text)}")
        except Exception as error:
            raise Exception(f"Failed to parse response: {request.text} Error: {error}")

        if response_message.lower() != "success":
            raise Exception(f"{response_message}")

        return response

    # Fetch the data from the PowerOcean device, which then constitues the Sensors
    def fetch_data(self):
        # curl 'https://api-e.ecoflow.com/provider-service/user/device/detail?sn={self.sn}}' \
        # -H 'authorization: Bearer {self.token}'

        url = self.url_user_fetch
        try:
            headers = {"authorization": f"Bearer {self.token}"}
            request = requests.get(self.url_user_fetch, headers=headers, timeout=30)
            response = self.get_json_response(request)

            _LOGGER.debug(f"{response}")
            _LOGGER.debug(f"{response['data']}")

            # Proceed to parsing
            return self._get_sensors(response)

        except ConnectionError:
            error = f"ConnectionError in fetch_data: Unable to connect to {url}. Device might be offline."
            _LOGGER.warning(error + ISSUE_URL_ERROR_MESSAGE)
            raise IntegrationError(error)

        except RequestException as e:
            error = f"RequestException in fetch_data: Error while fetching data from {url}: {e}"
            _LOGGER.warning(error + ISSUE_URL_ERROR_MESSAGE)
            raise IntegrationError(error)

    def _get_sensors(self, response):
        # 1. get most important data first
        sensors = self.__get_base_sensors(response["data"])

        # 2. get info from batteries  => JTS1_BP_STA_REPORT
        sens_bat = self.__get_battery_sensors(response["data"]["quota"]["JTS1_BP_STA_REPORT"])
        dict.update(sensors, sens_bat)

        # TODO: mpptHeartBeat collect from JTS1_EMS_HEARTBEAT
        #       response["data"]["quota"]["JTS1_EMS_HEARTBEAT"]['mpptHeartBeat']

        # TODO: JTS1_EMS_CHANGE_REPORT  => we may not need this
        #       response["data"]["quota"]["JTS1_EMS_CHANGE_REPORT"]

        return sensors

    def __get_base_sensors(self, d):
        # sens_all = ['sysLoadPwr', 'sysGridPwr', 'mpptPwr', 'bpPwr', 'bpSoc', 'sysBatChgUpLimit', 'sysBatDsgDownLimit',
        #             'sysGridSta', 'sysOnOffMachineStat', 'online', 'todayElectricityGeneration',
        #             'monthElectricityGeneration', 'yearElectricityGeneration', 'totalElectricityGeneration',
        #             'systemName', 'createTime', 'location', 'timezone', 'quota']
        sens_select = ['sysLoadPwr', 'sysGridPwr', 'mpptPwr', 'bpPwr', 'bpSoc', 'online',
                       'todayElectricityGeneration', 'monthElectricityGeneration',
                       'yearElectricityGeneration', 'totalElectricityGeneration',
                       'systemName', 'createTime']
        sensors = dict()
        for key, value in d.items():
            if key in sens_select:   # use only sensors in sens_select
                if not isinstance(value, dict):
                    # default uid, unit and descript
                    unique_id = f"{self.sn}_{key}"
                    unit_tmp = ""
                    description_tmp = {key}

                    if key == "sysLoadPwr":
                        unit_tmp = "W"
                        description_tmp = "Hausnetz"
                    if key == "sysGridPwr":
                        unit_tmp = "W"
                        description_tmp = "Stromnetz"
                    if key == "mpptPwr":
                        unit_tmp = "W"
                        description_tmp = "Solarertrag"
                    if key == "bpPwr":
                        unit_tmp = "W"
                        description_tmp = "Batterieleistung"
                    if key == "bpSoc":
                        unit_tmp = "%"
                        description_tmp = "Ladezustand der Batterie"
                    if key == "online":
                        unit_tmp = ""
                        description_tmp = "Online"
                    if key == "systemName":
                        unit_tmp = ""
                        description_tmp = "System Name"
                    if key == "createTime":
                        unit_tmp = ""
                        description_tmp = "Installations Datum"

                    if "Energy" in key:
                        unit_tmp = "Wh"
                    if "Generation" in key:
                        unit_tmp = "kWh"

                    sensors[unique_id] = PowerOceanEndPoint(
                        internal_unique_id=unique_id,
                        serial=self.sn,
                        name=f"{self.sn}_{key}",
                        friendly_name=key,
                        value=value,
                        unit=unit_tmp,
                        description=description_tmp
                    )

        return sensors

    def __get_battery_sensors(self, d):
        removed = d.pop('')  # first element is empty
        keys = list(d.keys())
        n_bat = len(keys) - 1  # number of batteries found

        sensors = dict()

        # collect updateTime
        key = 'updateTime'
        value = d[key]
        unique_id = f"{self.sn}_{key}"
        sensors[unique_id] = PowerOceanEndPoint(
            internal_unique_id=unique_id,
            serial=self.sn,
            name=f"{self.sn}_{key}",
            friendly_name=key,
            value=value,
            unit="",
            description="Letzte Aktualisierung"
        )

        # loop over N batteries
        batts = keys[1:]
        ibat = 0
        bat_sens_select = ['bpPwr', 'bpSoc', 'bpSoh', 'bpVol', 'bpAmp','bpCycles', 'bpSysState']
        for ibat, bat in enumerate(batts):
            d_bat = json_loads(d[bat])
            for key, value in d_bat.items():
                if key in bat_sens_select:
                    # default uid, unit and descript
                    unique_id = f"{self.sn}_{bat}_{key}"
                    unit_tmp = ""
                    description_tmp = f"Battery{ibat+1}_{key}"

                    if key == "bpPwr":
                        unit_tmp = "W"
                        description_tmp = f"Battery{ibat+1} Leistung"

                    if key == "bpVol":
                        unit_tmp = "V"
                        description_tmp = f"Battery{ibat+1} Spannung"

                    if key == "bpAmp":
                        unit_tmp = ""
                        description_tmp = f"Battery{ibat+1} Ampere"

                    if key == "bpCycles":
                        unit_tmp = ""
                        description_tmp = f"Battery{ibat+1} Ladezyklen"

                    sensors[unique_id] = PowerOceanEndPoint(
                        internal_unique_id=unique_id,
                        serial=self.sn,
                        name=f"{self.sn}_bat{ibat+1}_{key}",
                        friendly_name=key,
                        value=value,
                        unit=unit_tmp,
                        description=description_tmp
                    )

        # create sensor for number of batteries
        key = 'number_of_batteries'
        unique_id = f"{self.sn}_{key}"
        unit_tmp = ""
        description_tmp = "Anzahl der Batterien"
        sensors[unique_id] = PowerOceanEndPoint(
            internal_unique_id=unique_id,
            serial=self.sn,
            name=f"{self.sn}_{key}",
            friendly_name=key,
            value=n_bat,
            unit=unit_tmp,
            description=description_tmp,
        )

        return sensors


class AuthenticationFailed(Exception):
    # TODO:
    """Exception to indicate authentication failure."""
