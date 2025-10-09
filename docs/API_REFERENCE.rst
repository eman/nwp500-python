API Reference
=============

This document provides the complete REST API reference for the Navien Smart Control API, generated from the OpenAPI specification.

Overview
--------

The Navien Smart Control API provides a RESTful interface for managing and controlling Navien NWP500 water heaters. The API uses JWT-based authentication and returns JSON responses.

**Base URL**: ``https://nlus.naviensmartcontrol.com/api/v2.1``

**Version**: 2.1.0

Authentication
--------------

The API uses JWT (JSON Web Tokens) for authentication:

1. **Sign-In**: POST to ``/user/sign-in`` with email and password
2. **Receive Tokens**: Get ``idToken``, ``accessToken``, and ``refreshToken``
3. **Authorize Requests**: Include ``accessToken`` in the ``authorization`` header (lowercase, no "Bearer" prefix)
4. **Refresh Token**: POST to ``/auth/refresh`` with ``refreshToken`` when ``accessToken`` expires

.. note::
   The Navien API uses a non-standard authorization header format. The header name is lowercase ``authorization`` (not ``Authorization``), and the token value is sent directly without the ``Bearer`` prefix.

API Endpoints
-------------

.. openapi:: openapi.yaml
