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

1. **Sign In** - POST credentials to ``/user/sign-in``
2. **Receive Tokens** - Get ``idToken``, ``accessToken``, ``refreshToken``
3. **Use Token** - Include ``accessToken`` in ``authorization`` header
4. **Refresh** - POST ``refreshToken`` to ``/auth/refresh`` before expiry

Token Lifetimes
---------------

* **Access Token**: 3600 seconds (1 hour)
* **Refresh Token**: Used to obtain new access tokens
* **AWS Credentials**: Included with tokens for MQTT access

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

* ``userId`` (string, required) - User email address
* ``offset`` (integer) - Pagination offset (default: 0)
* ``count`` (integer) - Number of devices to return (default: 20, max:
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

**Response:** Same as device object in ``/device/list``

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
           "deviceGroup": "NWP500"
         }
       ]
     }
   }

GET /device/tou
^^^^^^^^^^^^^^^

Get Time-of-Use (TOU) information for a device.

**Authentication Required:** Yes

**Query Parameters:**

* ``macAddress`` (string, required) - Device MAC address
* ``additionalValue`` (string, required) - Additional device identifier
* ``controllerId`` (string, required) - Controller ID
* ``userId`` (string, required) - User email
* ``userType`` (string) - User type (default: "O")

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

* :doc:`mqtt_protocol` - MQTT protocol for real-time communication
* :doc:`../python_api/auth_client` - Python authentication client
* :doc:`../python_api/api_client` - Python REST API client
