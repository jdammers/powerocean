"""ecoflow.py: API for PowerOcean integration."""
import requests
import base64
import json

from collections import namedtuple
from homeassistant.exceptions import IntegrationError
from requests.exceptions import RequestException, Timeout

from .const import _LOGGER, ISSUE_URL_ERROR_MESSAGE
# from const import _LOGGER, ISSUE_URL_ERROR_MESSAGE


# TODO: -----------------------------------------------------
#    TESTING  - put credentials here
# sn = 'HJ31ZDH4ZF730017'
# username = 'j.dammers@web.de'
# password = 'SK8#EcoFlow!'
# TODO:  end of testing -------------------------------------




# Better storage of PowerOcean endpoint
PowerOceanEndPoint = namedtuple(
    "PowerOceanEndPoint",
    "internal_unique_id, serial, name, friendly_name, value, unit, description",
)


# ecoflow_api to detect device and get device info, fetch the actual data from the PowerOcean device, and parse it
class ecoflow_api:
    def __init__(self, serialnumber, username, password):
        self.sn = serialnumber
        self.session = requests.Session()
        self.device = None
        self.login_url = None
        self.auth_url = None
        self.fetch_url = None

        self.ecoflow_username = username
        self.ecoflow_password = password
        self.user_id = None
        self.token = None
        self.mqtt_url = "mqtt.mqtt.com"
        self.mqtt_port = 8883
        self.mqtt_username = None
        self.mqtt_password = None



    def authorize(self):
        url = "https://api.ecoflow.com/auth/login"
        self.login_url = url
        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {"email": self.ecoflow_username,
                "password": base64.b64encode(self.ecoflow_password.encode()).decode(),
                "scene": "IOT_APP",
                "userType": "ECOFLOW"}

        _LOGGER.info(f"Login to EcoFlow API {url}")
        request = requests.post(url, json=data, headers=headers)
        response = self.get_json_response(request)

        try:
            self.token = response["data"]["token"]
            self.user_id = response["data"]["user"]["userId"]
            user_name = response["data"]["user"].get("name", "<no user name>")
        except KeyError as key:
            raise Exception(f"Failed to extract key {key} from response: {response}")

        _LOGGER.info(f"Successfully logged in: {user_name}")

        url = "https://api.ecoflow.com/iot-auth/app/certification"
        self.auth_url = url
        headers = {"lang": "en_US", "authorization": f"Bearer {self.token}"}
        data = {"userId": self.user_id}

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



    def detect_device(self):
        try:
            # # curl 'https://api-e.ecoflow.com/auth/login' \
            # # -H 'content-type: application/json' \
            # # --data-raw '{"userType":"ECOFLOW","scene":"EP_ADMIN","email":"","password":""}'
            #
            # url = f"https://api-e.ecoflow.com/auth/login"
            # headers = {"lang": "en_US", "content-type": "application/json"}
            # data = {
            #     "email": self.ecoflow_username,
            #     "password": base64.b64encode(self.password.encode()).decode(),
            #     "scene": "IOT_APP",
            #     "userType": "ECOFLOW",
            # }
            #
            # _LOGGER.debug(f"Login to EcoFlow API {url}")
            # request = requests.post(url, json=data, headers=headers, timeout=30)
            # response = self.get_json_response(request)
            # _LOGGER.debug(f"{response}")
            #
            # try:
            #     self.token = response["data"]["token"]
            # except KeyError as key:
            #     raise Exception(
            #         f"Failed to extract key {key} from response: {response}"
            #     )


            self.authorize()
            # TODO: Update with current data
            self.device = {
                "product": "PowerOcean",
                "vendor": "Ecoflow",
                "serial": self.sn,
                "version": "5.1.8",
                "build": "13",
                "name": "PowerOcean",
                "features": "Photovoltaik",
            }

        except ConnectionError:
            error = f"Unable to connect to {self.login_url}. Device might be offline."
            _LOGGER.warning( error + ISSUE_URL_ERROR_MESSAGE )
            raise IntegrationError(error)
            return None

        except RequestException as e:
            error = f"Error detecting PowerOcean device - {e}"
            _LOGGER.error(error + ISSUE_URL_ERROR_MESSAGE)
            raise IntegrationError(error)
            return None

        return self.device

    def get_json_response(self, request):
        if request.status_code != 200:
            raise Exception(f"Got HTTP status code {request.status_code}: {request.text}")
        try:
            response = json.loads(request.text)
            #response = request.json()
            response_message = response["message"]
        except KeyError as key:
            raise Exception(f"Failed to extract key {key} from {response}")
        except Exception as error:
            raise Exception(f"Failed to parse response: {request.text} Error: {error}")

        if response_message.lower() != "success":
            raise Exception(f"{response_message}")

        return response

    # Fetch the data from the PowerOcean device, which then constitues the Sensors
    def fetch_data(self):
        # curl 'https://api-e.ecoflow.com/provider-service/user/device/detail?sn={self.sn}}' \
        # -H 'authorization: Bearer {self.token}'

        url = f"https://api-e.ecoflow.com/provider-service/user/device/detail?sn={self.sn}"
        self.fetch_url = url

        try:
            headers = {"authorization": f"Bearer {self.token}"}
            request = requests.get(self.fetch_url, headers=headers, timeout=30)
            response = self.get_json_response(request)

            _LOGGER.debug(f"{response}")

            # Proceed to parsing
            return self.__parse_data(response)

        except ConnectionError:
            error = f"ConnectionError in fetch_data: Unable to connect to {url}. Device might be offline."
            _LOGGER.warning(error + ISSUE_URL_ERROR_MESSAGE)
            raise IntegrationError(error)
            return None

        except RequestException as e:
            error = f"RequestException in fetch_data: Error while fetching data from {url}: {e}"
            _LOGGER.warning(error + ISSUE_URL_ERROR_MESSAGE)
            raise IntegrationError(error)
            return None

    def __parse_data(self, response):
        # Implement the logic to parse the response from the PowerOcean device
        entities = {}
        for key, value in response["data"].items():
            if key == "quota":
                continue
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

            if "Energy" in key:
                unit_tmp = "Wh"
            if "Generation" in key:
                unit_tmp = "kWh"

            entities[unique_id] = PowerOceanEndPoint(
                    internal_unique_id=unique_id,
                    serial=self.sn,
                    name=f"{self.sn}_{key}",
                    friendly_name=key,
                    value=value,
                    unit=unit_tmp,
                    description=description_tmp
            )

        # TODO: JTS1_BP_STA_REPORT  => this is the one we need
        entities = self.__get_battery_entities(entities, response["data"]["quota"]["JTS1_BP_STA_REPORT"])


        # TODO: JTS1_EMS_CHANGE_REPORT  => we may not need this
        # dict_items = response["data"]["quota"]["JTS1_EMS_CHANGE_REPORT"].items()
        # self.entities = self.__parse_from_dict(data, dict_items)


        return entities

    def __get_battery_entities(self, entities, dict_bat):
        keys = list(dict_bat.keys())
        bat_entities = {}

        # get updateTime
        ut = dict(updateTime=dict_bat['updateTime'])
        bat_entities = self.__parse_from_dict(bat_entities, ut.items())
        # get data from all batteries
        for k in keys[2:]:
            bat = json.loads(dict_bat[k])
            bat_entities  = self.__parse_from_dict(bat_entities, bat.items(), uid=k)
            dict.update(entities, bat_entities)

        return entities


    def __parse_from_dict(self, data, dict_items, uid=None):
        for key, value in dict_items:
            if not uid:
                unique_id = f"{self.sn}_{key}"
            else:
                unique_id = f"{uid}_{key}"
            unit_tmp = ""
            description_tmp = key
            print(unique_id, description_tmp)

            if key == "bpTotalChgEnergy":
                unit_tmp = "Wh"
                description_tmp = "Batterie Laden Total"
            if key == "bpTotalDsgEnergy":
                unit_tmp = "Wh"
                description_tmp = "Batterie Entladen Total"
            if "LowVol" in key:
                unit_tmp = "V"
            if "HighVol" in key:
                unit_tmp = "V"
            if "OverVol" in key:
                unit_tmp = "V"

            # TODO: bpTemp is a list of 9 temperature values => compute average and store mean value
            if key != 'bpTemp':
                data[unique_id] = PowerOceanEndPoint(
                    internal_unique_id=unique_id,
                    serial=self.sn,
                    name=f"{self.sn}_{key}",
                    friendly_name=key,
                    value=value,
                    unit=unit_tmp,
                    description=description_tmp,
                )

        return data


class AuthenticationFailed(Exception):
    # TODO:
    """Exception to indicate authentication failure."""



# ef = ecoflow_api(sn, username, password)
# ef.detect_device()
# data = ef.fetch_data()