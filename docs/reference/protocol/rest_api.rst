====================
REST API Protocol
====================

This document describes the Navien Smart Control REST API protocol based
on the OpenAPI 3.1 specification.

.. warning::
   This document describes the underlying REST API protocol. Most users should use the
   Python client library (:doc:`../python_api/api_client`) instead of using the API directly.

Base URL
========

.. code-block::

   https://nlus.naviensmartcontrol.com/api/v2.1

All endpoints are relative to this base URL.

Authentication
==============

The API uses JWT (JSON Web Tokens) for authentication with a
**non-standard header format**:

.. important::
   **Non-Standard Authorization Header**
   
   * Header name: **lowercase** ``authorization`` (not ``Authorization``)
   * Header value: **raw token** (no ``Bearer`` prefix)
   
   Example: ``{"authorization": "eyJraWQi..."}``
   
   This differs from standard OAuth2/JWT authentication!

Authentication Flow
-------------------

1. **Sign In**: POST credentials to ``/user/sign-in``
2. **Receive Tokens**: Get ``idToken``, ``accessToken``, ``refreshToken``
   and AWS credentials
3. **Use Token**: Include ``accessToken`` in ``authorization`` header
4. **Refresh**: POST ``refreshToken`` to ``/auth/refresh`` before expiry
5. **Renew AWS credentials**: POST to ``/auth/session/refresh`` (AWS
   credentials only) or ``/user/secured-sign-in`` (user info plus, in
   practice, the same AWS credential fields) with the access token; the
   password is only needed if both fail

Token Lifetimes
---------------

* **Access Token**: 3600 seconds (1 hour)
* **Refresh Token**: Used to obtain new access tokens
* **AWS Credentials**: Included with tokens for MQTT access; expire
  separately (``authorizationExpiresIn``) and are not renewed by
  ``/auth/refresh``

Endpoints
=========

Authentication Endpoints
------------------------

POST /user/sign-in
^^^^^^^^^^^^^^^^^^

Authenticate user and obtain tokens.

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "password": "your_password"
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "userInfo": {
         "userType": "O",
         "userFirstName": "John",
         "userLastName": "Doe",
         "userStatus": "NORMAL",
         "userSeq": 36283
       },
       "token": {
         "idToken": "eyJraWQ...",
         "accessToken": "eyJraWQ...",
         "refreshToken": "eyJraWQ...",
         "authenticationExpiresIn": 3600,
         "accessKeyId": "ASIA...",
         "secretKey": "abc123...",
         "sessionToken": "IQoJ...",
         "authorizationExpiresIn": 3600
       },
       "legal": []
     }
   }

**Error Response (401 Unauthorized):**

.. code-block:: json

   {
     "code": 401,
     "msg": "Invalid credentials"
   }

POST /auth/refresh
^^^^^^^^^^^^^^^^^^

Refresh access token using refresh token.

**Request Body:**

.. code-block:: json

   {
     "refreshToken": "eyJraWQ..."
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "idToken": "eyJraWQ...",
       "accessToken": "eyJraWQ...",
       "refreshToken": "eyJraWQ...",
       "authenticationExpiresIn": 3600,
       "accessKeyId": "ASIA...",
       "secretKey": "abc123...",
       "sessionToken": "IQoJ...",
       "authorizationExpiresIn": 3600
     }
   }

.. note::
   This endpoint does not renew the AWS credentials; the library keeps the
   stored ones when the response omits them. Use ``/auth/session/refresh``
   to renew them.

POST /auth/session/refresh
^^^^^^^^^^^^^^^^^^^^^^^^^^

Renew the AWS (SigV4) credentials used for MQTT without a password. The
NaviLink app calls this when the MQTT connection fails with an
authentication error.

**Authentication Required:** Yes (``authorization: <accessToken>``)

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com"
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "accessKeyId": "ASIA...",
       "secretKey": "abc123...",
       "sessionToken": "IQoJ...",
       "authorizationExpiresIn": 3600
     }
   }

Each ``data`` key is optional; the app overwrites only the keys present
and keeps its stored values for the rest. JWT tokens are not returned.

POST /user/secured-sign-in
^^^^^^^^^^^^^^^^^^^^^^^^^^

Sign in with a previously issued access token instead of the password. The
NaviLink app tries this first on auto-login and falls back to
``/user/sign-in`` if it fails or no token is stored.

**Authentication Required:** Yes (``authorization: <accessToken>``)

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com"
   }

**Response (200 OK):** identical in shape to ``/user/sign-in``
(``data.userInfo``, ``data.token`` with JWT and AWS credentials,
``data.legal``).

**Error Response (401 Unauthorized):** the stored token was rejected; sign
in with the password.

Device Management Endpoints
----------------------------

POST /device/list
^^^^^^^^^^^^^^^^^

List all devices registered to the user.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "offset": 0,
     "count": 20
   }

**Parameters:**

* ``userId`` (string, required): User email address
* ``offset`` (integer): Pagination offset (default: 0)
* ``count`` (integer): Number of devices to return (default: 20, max:
  20)

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": [
       {
         "deviceInfo": {
           "homeSeq": 12345,
           "macAddress": "04786332fca0",
           "additionalValue": "...",
           "deviceType": 52,
           "deviceName": "Water Heater",
           "connected": 2,
           "installType": "indoor"
         },
         "location": {
           "state": "CA",
           "city": "San Francisco",
           "address": "123 Main St",
           "latitude": 37.7749,
           "longitude": -122.4194,
           "altitude": 16.0
         }
       }
     ]
   }

**Response Fields:**

* ``homeSeq``: Unique home/location identifier assigned by the Navien cloud system.
  Used in MQTT topic paths (format: ``cmd/{deviceType}/{homeSeq}/{userSeq}/...``)
  to route all device commands and status messages to the correct home installation.
* Other fields as documented in :py:class:`nwp500.models.DeviceInfo`

POST /device/info
^^^^^^^^^^^^^^^^^

Get detailed information about a specific device.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "userId": "user@example.com"
   }

**Response:** The device object from ``/device/list`` without ``error``,
plus two sections the list omits:

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "deviceInfo": {"homeSeq": 25004, "deviceName": "NWP500",
                      "deviceType": 52, "installType": "R", "connected": 2},
       "location": {"state": "California", "city": "Anytown",
                    "address": "123 Main Street",
                    "latitude": 38.011845, "longitude": -122.54772},
       "installer": {
         "installerId": null,
         "installerFirstName": null,
         "installerLastName": null,
         "installerPhoneNumber": null
       },
       "alarmInfo": {"isErrorAlarm": 1, "isDescalingAlarm": 1, "isEtcAlarm": 1},
       "descaling": {"descalingStartTime": null, "descalingEndTime": null}
     }
   }

* ``installer``: the installer linked to the device, every field ``null``
  when there is none (:py:class:`nwp500.models.DeviceInstaller`).
* ``alarmInfo``: push-notification flags, **1 = on, 2 = off** (the
  opposite of the device's on/off flags; see ``/user/get-push-settings``
  below). A flag the cloud does not report is simply absent
  (:py:class:`nwp500.models.PushSettings`).

POST /device/firmware/info
^^^^^^^^^^^^^^^^^^^^^^^^^^

Get firmware information for a device.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "userId": "user@example.com"
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "firmwares": [
         {
           "macAddress": "04786332fca0",
           "additionalValue": "...",
           "deviceType": 52,
           "curSwCode": 1,
           "curVersion": 184614912,
           "downloadedVersion": null,
           "deviceGroup": null
         }
       ]
     }
   }

``deviceGroup`` is ``null`` for a stand-alone unit; the NaviLink app reads
it as ``{"groupSeq": 7, "unitNum": 2}`` for a grouped one and also reads a
top-level ``deviceGroupUnitNo`` (:py:class:`nwp500.models.FirmwareInfo`).

POST /firmware/info
^^^^^^^^^^^^^^^^^^^

Describe one firmware image by the ``curSwCode``/``curVersion`` (or
``downloadedVersion``) pair from ``/device/firmware/info``. The NaviLink
app shows ``description`` on its update screen and ``runTime`` as the
estimated update duration in minutes (new in NaviLink 2.04.00).

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {"swCode": 33556241, "swVersion": 167837696}

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "description": "...",
       "modelNumber": 1,
       "modelType": 2,
       "productFamily": 3,
       "registerAt": 1700000000000,
       "runTime": 15,
       "swCode": 33556241,
       "swVersion": 167837696
     }
   }

Python: :py:meth:`nwp500.NavienAPIClient.get_firmware_detail`.

POST /device/change-info
^^^^^^^^^^^^^^^^^^^^^^^^

Rename a device or update its installation type and location.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "deviceInfo": {
       "macAddress": "04786332fca0",
       "additionalValue": "...",
       "deviceType": 52,
       "deviceName": "Garage Heater",
       "installType": "R"
     },
     "location": {
       "state": "California",
       "city": "Anytown",
       "address": "123 Main Street",
       "latitude": 38.011845,
       "longitude": -122.54772,
       "altitude": 16.0
     }
   }

The app omits ``installType`` when empty, omits ``location`` entirely
unless at least one of ``state``/``city``/``address`` is set, and inside it
leaves out empty strings and zero coordinates.

**Response (200 OK):** ``{"code": 200, "msg": "SUCCESS"}``

Python: :py:meth:`nwp500.NavienAPIClient.update_device_info`.

POST /device/simple-list
^^^^^^^^^^^^^^^^^^^^^^^^

A trimmed device list. The app uses it for its product-management screen
(``targetUserId`` = the signed-in user) and for an installer viewing an
owner's devices (``targetUserId`` = the owner's ID).

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "targetUserId": "user@example.com",
     "offset": 0,
     "count": 20
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": [
       {
         "macAddress": "04786332fca0",
         "additionalValue": "...",
         "deviceType": 52,
         "modelTypeCode": null,
         "deviceName": "NWP500"
       }
     ]
   }

Python: :py:meth:`nwp500.NavienAPIClient.list_simple_devices`.

POST /device/error/list
^^^^^^^^^^^^^^^^^^^^^^^

Faults the cloud has recorded for a device. The NaviLink app only calls
this from its installer error-list screen and sends the signed-in user's
ID as ``installerId``; whether the backend accepts an owner's ID is
untested. Pages are keyed by the last entry's ``errorOccuredTime``, sent
back as ``continuousKey`` (omitted on the first page).

**Authentication Required:** Yes

Installer accounts only: an owner account receives
``404 COMMON_NOT_AUTHORIZED`` (checked live).

**Request Body:**

.. code-block:: json

   {
     "installerId": "installer@example.com",
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "continuousKey": 1733572682000,
     "count": 20
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "timeZone": "America/Los_Angeles",
       "errorInfo": [
         {
           "channelNumber": 1,
           "unitType": 1,
           "errorCode": 96,
           "subError": 0,
           "errorOccuredTime": 1733572682000
         }
       ]
     }
   }

``errorOccuredTime`` is epoch milliseconds. Python:
:py:meth:`nwp500.NavienAPIClient.get_error_history`.

POST /device/filter/change-info and POST /device/cip/change-info
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Record the date the air filter was replaced, or a CIP (clean-in-place /
descaling) service was done. Both take the same body. ``maintenanceDate``
is ``YYYY-M-D`` **without zero padding**: the app concatenates its date
picker's integers.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "deviceType": 52,
     "maintenanceDate": "2025-3-7"
   }

**Response (200 OK):** ``{"code": 200, "msg": "SUCCESS"}``

Python: :py:meth:`nwp500.NavienAPIClient.record_filter_change`,
:py:meth:`nwp500.NavienAPIClient.record_cip_change`.

POST /device/filter/history and POST /device/cip/history
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

List the dates recorded above, newest first.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "offset": 0,
     "count": 20,
     "macAddress": "04786332fca0",
     "additionalValue": "..."
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": [
       {"maintenanceDate": "2025-3-7", "registerAt": 1741305600}
     ]
   }

The app reads ``registerAt`` as an integer; its unit is not documented.
Python: :py:meth:`nwp500.NavienAPIClient.get_filter_history`,
:py:meth:`nwp500.NavienAPIClient.get_cip_history`.

GET /device/preferences/format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Unit display preferences stored for a device. The app serialises its
request object and appends it to the URL as a query string.

**Authentication Required:** Yes

.. note::

   Not accepted for the NWP500: the cloud answers ``400 COMMON_BAD_REQUEST``
   for device type 52 whatever the parameters (checked live). The app only
   calls this for the IoT-module hydro unit (device type 8).

**Query Parameters:**

* ``macAddress`` (string, required)
* ``additionalValue`` (string, required)
* ``modelTypeCode`` (integer): from the device feature; omitted when
  unknown

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": [
       {
         "modelTypeCode": 1,
         "pressureDisplayFormat": "P",
         "temperatureDisplayFormat": "F"
       }
     ]
   }

The app uses the first entry. ``temperatureDisplayFormat`` is ``"F"`` or
``"C"``; ``pressureDisplayFormat`` is ``"P"`` (psi) or ``"M"`` (metric).
Those four are the only values the app compares against or writes.

POST /device/preferences/format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Store the display preferences.

**Request Body:**

.. note::

   Not accepted for the NWP500: the cloud answers ``400 COMMON_BAD_REQUEST``
   for device type 52 whatever the parameters (checked live). The app only
   calls this for the IoT-module hydro unit (device type 8).

.. code-block:: json

   {
     "macAddress": "04786332fca0",
     "additionalValue": "...",
     "modelTypeCode": 1,
     "pressureDisplayFormat": "M",
     "temperatureDisplayFormat": "C"
   }

**Response (200 OK):** ``{"code": 200, "msg": "SUCCESS"}``

Python: :py:meth:`nwp500.NavienAPIClient.get_display_preferences`,
:py:meth:`nwp500.NavienAPIClient.set_display_preferences`.

DELETE /device/tou
^^^^^^^^^^^^^^^^^^

Remove the TOU rate plan from a device. The app serialises the same
``TouRequest`` object it sends to ``PUT /device/tou`` and appends it to the
URL as a query string (a DELETE has no body). It sends ``userId``,
``userType``, ``registerPath`` and ``sourceType`` from the current plan,
then ``controllerId`` for a plan registered over Bluetooth
(``registerPath`` = ``"bt"``) or ``macAddress`` and ``additionalValue``
otherwise.

**Authentication Required:** Yes

**Query Parameters:**

* ``userId``, ``userType`` (string, required)
* ``registerPath`` (string): ``"wifi"`` or ``"bt"``
* ``sourceType`` (string): ``"openei"``
* ``macAddress``, ``additionalValue`` (string): WiFi-registered plan
* ``controllerId`` (string): Bluetooth-registered plan

**Response (200 OK):** ``{"code": 200, "msg": "SUCCESS"}``

Python: :py:meth:`nwp500.NavienAPIClient.delete_tou`.

GET /device/tou/manufacture-id
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The manufacture ID the TOU service holds for a device. The app shows
"N/A" when it is ``"000000000000000"``.

**Authentication Required:** Yes

``controllerId`` is the controller serial number from the device feature
(the same value ``GET /device/tou`` takes); any other value returns
``500 INTERNAL_SERVER_ERROR``.

**Query Parameters:** ``userId``, ``macAddress``, ``additionalValue``,
``controllerId`` (all strings, required)

**Response (200 OK):**

.. code-block:: json

   {"code": 200, "msg": "SUCCESS", "data": {"manufactureId": "6760E2532669023"}}

Python: :py:meth:`nwp500.NavienAPIClient.get_manufacture_id`.

GET /device/tou
^^^^^^^^^^^^^^^

Get Time-of-Use (TOU) information for a device.

**Authentication Required:** Yes

**Query Parameters:**

* ``macAddress`` (string, required): Device MAC address
* ``additionalValue`` (string, required): Additional device identifier
* ``controllerId`` (string, required): Controller ID
* ``userId`` (string, required): User email
* ``userType`` (string): User type (default: "O")

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "registerPath": "...",
       "sourceType": "...",
       "touInfo": {
         "controllerId": "...",
         "manufactureId": "...",
         "name": "Pacific Gas & Electric",
         "utility": "PG&E",
         "zipCode": 94102,
         "schedule": [
           {
             "season": 448,
             "interval": [
               {
                 "week": 62,
                 "startHour": 9,
                 "startMinute": 0,
                 "endHour": 17,
                 "endMinute": 0,
                 "priceMin": 10,
                 "priceMax": 25,
                 "decimalPoint": 2
               }
             ]
           }
         ]
       }
     }
   }

POST /app/update-push-token
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Update push notification token (optional).

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "pushToken": "...",
     "modelName": "Python Client",
     "appVersion": "1.0.0",
     "os": "Python",
     "osVersion": "3.9+"
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS"
   }

User Endpoints
--------------

POST /user/info
^^^^^^^^^^^^^^^

The signed-in user's profile. A superset of the ``userInfo`` block in the
sign-in response, adding the phone number and e-mail.

**Authentication Required:** Yes

**Request Body:** ``{"userId": "user@example.com"}``

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {
       "userType": "O",
       "userFirstName": "Jane",
       "userLastName": null,
       "userPhoneNumber": "5551234",
       "userSeq": 36283,
       "userEmail": "user@example.com"
     }
   }

The app treats a ``null`` last name as ``""``. Python:
:py:meth:`nwp500.NavienAPIClient.get_user_profile`.

POST /user/get-push-settings
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Which push notifications are enabled for one device.

**Authentication Required:** Yes

**Request Body:**

.. code-block:: json

   {
     "userId": "user@example.com",
     "macAddress": "04786332fca0",
     "additionalValue": "..."
   }

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {"isErrorAlarm": 1, "isDescalingAlarm": 2, "isEtcAlarm": 1}
   }

.. important::

   **1 = on, 2 = off.** The NaviLink app sends ``isChecked() ? 1 : 2``.
   This is the reverse of the device's own on/off flags (1 = off,
   2 = on) documented in :doc:`data_conversions`.

POST /user/set-push-settings
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Same body as ``get-push-settings`` plus any of ``isErrorAlarm``,
``isDescalingAlarm`` and ``isEtcAlarm`` as 1 or 2. The app leaves a key
out when it has nothing to say (it omits ``isDescalingAlarm`` for a
member account).

**Response (200 OK):** ``{"code": 200, "msg": "SUCCESS"}``

Python: :py:meth:`nwp500.NavienAPIClient.get_push_settings`,
:py:meth:`nwp500.NavienAPIClient.set_push_settings`.

App Endpoints
-------------

POST /app/version
^^^^^^^^^^^^^^^^^

Latest and minimum supported NaviLink versions. The app calls this on its
splash screen, **without** an ``authorization`` header.

**Authentication Required:** No

**Request Body:** ``{"os": "A"}`` (Android; the only value the app sends)

**Response (200 OK):**

.. code-block:: json

   {
     "code": 200,
     "msg": "SUCCESS",
     "data": {"appVersion": "2.04.00", "appForceVersion": "2.00.00"}
   }

**Maintenance (403):** when the backend is down for maintenance the
response is a 403 whose ``data.serverCheckText`` carries the notice the
app displays (with literal ``\n`` sequences for line breaks):

.. code-block:: json

   {"code": 403, "msg": "...", "data": {"serverCheckText": "..."}}

Python: :py:meth:`nwp500.NavienAPIClient.get_app_version`.

Error Responses
===============

All error responses follow this format:

.. code-block:: json

   {
     "code": 404,
     "msg": "NOT_FOUND",
     "data": null
   }

Common Error Codes
------------------

.. list-table::
   :header-rows: 1
   :widths: 10 20 70

   * - Code
     - Meaning
     - Description
   * - 200
     - Success
     - Request completed successfully
   * - 400
     - Bad Request
     - Invalid request parameters
   * - 401
     - Unauthorized
     - Invalid or expired authentication token
   * - 403
     - Forbidden
     - User lacks permission for this resource
   * - 404
     - Not Found
     - Resource not found
   * - 500
     - Server Error
     - Internal server error

Rate Limiting
=============

The API does not currently publish specific rate limits. Best practices:

* Avoid polling endpoints more frequently than once per minute
* Use MQTT for real-time updates instead of polling REST API
* Implement exponential backoff for failed requests
* Cache responses when appropriate

Data Models
===========

See :doc:`../python_api/models` for complete Python data model documentation.

Example Usage
=============

Using curl
----------

Sign in:

.. code-block:: bash

   curl -X POST https://nlus.naviensmartcontrol.com/api/v2.1/user/sign-in \
     -H "Content-Type: application/json" \
     -d '{"userId":"user@example.com","password":"your_password"}'

List devices (with token):

.. code-block:: bash

   curl -X POST https://nlus.naviensmartcontrol.com/api/v2.1/device/list \
     -H "Content-Type: application/json" \
     -H "authorization: YOUR_ACCESS_TOKEN" \
     -d '{"userId":"user@example.com","offset":0,"count":20}'

Using Python
------------

See :doc:`../python_api/api_client` for the Python client documentation.

Related Documentation
=====================

* :doc:`mqtt_protocol`: MQTT protocol for real-time communication
* :doc:`../python_api/auth_client`: Python authentication client
* :doc:`../python_api/api_client`: Python REST API client
