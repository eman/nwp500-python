==============
Installation
==============

Requirements
============

* Python 3.9 or higher
* pip (Python package installer)
* Navien Smart Control account

Installing from PyPI
====================

The easiest way to install nwp500-python:

.. code-block:: bash

   pip install nwp500-python

This will install the library and all required dependencies.

Installing from Source
======================

For development or to get the latest features:

.. code-block:: bash

   git clone https://github.com/eman/nwp500-python.git
   cd nwp500-python
   pip install -e .

Development Installation
========================

To install with development dependencies (testing, linting, docs):

.. code-block:: bash

   git clone https://github.com/eman/nwp500-python.git
   cd nwp500-python
   pip install -e ".[dev]"

Dependencies
============

Core Dependencies
-----------------

The library requires:

* ``aiohttp>=3.8.0`` - Async HTTP client for REST API
* ``awsiotsdk>=1.20.0`` - AWS IoT SDK for MQTT
* ``pydantic>=2.0.0`` - Data validation and models

Optional Dependencies
---------------------

For development:

* ``pytest>=7.0.0`` - Testing framework
* ``pytest-asyncio>=0.21.0`` - Async test support
* ``pytest-cov>=4.0.0`` - Coverage reporting
* ``ruff>=0.1.0`` - Fast Python linter
* ``mypy>=1.0.0`` - Static type checking
* ``sphinx>=5.0.0`` - Documentation generation

Verification
============

Verify the installation:

.. code-block:: python

   import nwp500
   print(nwp500.__version__)

Or test with a simple script:

.. code-block:: python

   from nwp500 import NavienAuthClient, NavienAPIClient
   import asyncio

   async def test():
       async with NavienAuthClient("email@test.com", "pass") as auth:
           api = NavienAPIClient(auth)
           # This will fail with bad credentials, but proves import works
           try:
               await api.list_devices()
           except Exception as e:
               print(f"Library loaded successfully: {type(e).__name__}")

   asyncio.run(test())

Troubleshooting
===============

ImportError: No module named 'nwp500'
--------------------------------------

Make sure you installed the package:

.. code-block:: bash

   pip install nwp500-python

If using a virtual environment, ensure it's activated.

SSL/TLS Errors
--------------

If you get SSL certificate errors:

.. code-block:: bash

   # macOS
   /Applications/Python\ 3.x/Install\ Certificates.command

   # Linux (update certificates)
   sudo apt-get update && sudo apt-get install ca-certificates

AWS IoT Connection Issues
--------------------------

The MQTT client requires the AWS IoT SDK:

.. code-block:: bash

   pip install awsiotsdk>=1.20.0

Upgrading
=========

To upgrade to the latest version:

.. code-block:: bash

   pip install --upgrade nwp500-python

To upgrade to a specific version:

.. code-block:: bash

   pip install nwp500-python==X.Y.Z

Next Steps
==========

* :doc:`quickstart` - Get started with your first script
* :doc:`configuration` - Configure credentials and options
* :doc:`python_api/auth_client` - Learn about authentication
