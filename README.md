# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                |    Stmts |     Miss |   Branch |   BrPart |    Cover |   Missing |
|------------------------------------ | -------: | -------: | -------: | -------: | -------: | --------: |
| \_version.py                        |        1 |        0 |        0 |        0 |     100% |           |
| data\_logger.py                     |      169 |        0 |       24 |        0 |     100% |           |
| devices/\_\_init\_\_.py             |        8 |        0 |        0 |        0 |     100% |           |
| devices/coherent.py                 |       44 |        0 |        0 |        0 |     100% |           |
| devices/connections/\_\_init\_\_.py |        6 |        0 |        0 |        0 |     100% |           |
| devices/connections/base.py         |       76 |        0 |       14 |        0 |     100% |           |
| devices/connections/ethernet.py     |       47 |        0 |        0 |        0 |     100% |           |
| devices/connections/gpib.py         |       29 |        0 |        0 |        0 |     100% |           |
| devices/connections/prologix.py     |       33 |        0 |        0 |        0 |     100% |           |
| devices/connections/serial.py       |       72 |        0 |       18 |        0 |     100% |           |
| devices/e\_plus\_e.py               |       41 |        0 |        0 |        0 |     100% |           |
| devices/errors.py                   |        1 |        0 |        0 |        0 |     100% |           |
| devices/fluke.py                    |      158 |        0 |       12 |        0 |     100% |           |
| devices/ilx.py                      |       94 |        0 |        4 |        0 |     100% |           |
| devices/keithley.py                 |      115 |        0 |        6 |        0 |     100% |           |
| devices/keysight.py                 |      131 |        0 |        2 |        0 |     100% |           |
| endpoints/\_\_init\_\_.py           |        3 |        0 |        0 |        0 |     100% |           |
| endpoints/filewriter.py             |       66 |        0 |       14 |        0 |     100% |           |
| endpoints/mqtt.py                   |      113 |        0 |       28 |        0 |     100% |           |
| errors.py                           |        4 |        0 |        0 |        0 |     100% |           |
| factories/\_\_init\_\_.py           |        3 |        0 |        0 |        0 |     100% |           |
| factories/device\_factory.py        |       16 |        0 |        0 |        0 |     100% |           |
| factories/endpoint\_factory.py      |        5 |        0 |        0 |        0 |     100% |           |
| factories/generic\_factory.py       |       17 |        0 |        0 |        0 |     100% |           |
| logger/\_\_init\_\_.py              |        2 |        0 |        0 |        0 |     100% |           |
| logger/logger.py                    |      350 |        0 |       32 |        0 |     100% |           |
| **TOTAL**                           | **1604** |    **0** |  **154** |    **0** | **100%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/PatrickBaus/data_logger/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/PatrickBaus/data_logger/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FPatrickBaus%2Fdata_logger%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.