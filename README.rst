=============
nwp500-python
=============

|PyPI-v| |Python-versions| |CI-status| |Docs-status| |Code-style| |License|

Python library for Navien NWP500 Heat Pump Water Heater
========================================================

A complete Python library for monitoring and controlling the Navien NWP500 Heat Pump Water Heater through the Navilink cloud service.

* **Documentation:** https://nwp500-python.readthedocs.io/
* **Source:** https://github.com/eman/nwp500-python

Features
========
* **Complete Interface:** Full support for both REST API and real-time MQTT (AWS IoT).
* **Monitoring:** Real-time tracking of temperature, power usage, tank charge, and component status.
* **Control:** Remote control of target temperatures, operation modes, and vacation settings.
* **Advanced Features:** Native support for reservations, time-of-use (TOU) optimization, and anti-legionella cycles.
* **Type-Safe:** Built with Pydantic for robust data validation and unit handling.
* **Async/Await:** Modern asyncio-based implementation for high-performance integration.

Getting Started
===============

.. code-block:: bash

    pip install nwp500-python

Quick Example
-------------

.. code-block:: python

    from nwp500 import NavienAuthClient, NavienAPIClient

    async with NavienAuthClient("email@example.com", "password") as auth:
        api = NavienAPIClient(auth)
        devices = await api.list_devices()
        
        if devices:
            device = devices[0]
            print(f"Temperature: {device.status.dhw_temperature}°F")
            await api.set_device_temperature(device, 130)

Documentation
=============

* `Tutorials <https://nwp500-python.readthedocs.io/en/latest/tutorials/getting-started.html>`_: Start here if you're new to the library.
* `How-to Guides <https://nwp500-python.readthedocs.io/en/latest/how-to/index.html>`_: Practical step-by-step recipes for specific tasks.
* `Reference <https://nwp500-python.readthedocs.io/en/latest/reference/index.html>`_: Technical descriptions of the API, models, and protocol.
* `Explanation <https://nwp500-python.readthedocs.io/en/latest/explanation/index.html>`_: Understanding-oriented deep dives into the library's design and advanced features.

Contributing
============

We welcome contributions! Please see our `Contributing Guide <https://nwp500-python.readthedocs.io/en/latest/project/contributing.html>`_ for more details.

License
=======

This project is licensed under the MIT License. See the `LICENSE.txt <https://github.com/eman/nwp500-python/blob/main/LICENSE.txt>`_ file for details.

.. |PyPI-v| image:: https://img.shields.io/pypi/v/nwp500-python.svg
   :target: https://pypi.org/project/nwp500-python/
.. |Python-versions| image:: https://img.shields.io/pypi/pyversions/nwp500-python.svg
   :target: https://pypi.org/project/nwp500-python/
.. |CI-status| image:: https://github.com/eman/nwp500-python/actions/workflows/ci.yml/badge.svg
   :target: https://github.com/eman/nwp500-python/actions/workflows/ci.yml
.. |Docs-status| image:: https://readthedocs.org/projects/nwp500-python/badge/?version=latest
   :target: https://nwp500-python.readthedocs.io/en/latest/?badge=latest
.. |Code-style| image:: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
   :target: https://github.com/astral-sh/ruff
.. |License| image:: https://img.shields.io/pypi/l/nwp500-python.svg
   :target: https://opensource.org/licenses/MIT
