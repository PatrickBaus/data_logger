# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| \_version.py                   |        1 |        0 |        0 |        0 |    100% |           |
| data\_logger.py                |      149 |       12 |       22 |        4 |     89% |108, 210, 213-215, 294, 300-309, 313, 317, 323 |
| devices/\_\_init\_\_.py        |        9 |        0 |        0 |        0 |    100% |           |
| devices/async\_ethernet.py     |       59 |        6 |       10 |        3 |     87% |37, 41, 46, 83, 101-\>exit, 110-\>exit, 117-118 |
| devices/async\_serial.py       |       87 |       27 |       28 |        3 |     70% |69, 73, 133-142, 155-157, 169, 179-180, 184-195 |
| devices/coherent.py            |       49 |       31 |        2 |        0 |     35% |30, 33-34, 37-38, 43, 47, 50, 53-58, 61-68, 71, 74-79, 82-83 |
| devices/e\_plus\_e.py          |       46 |       31 |        2 |        0 |     31% |28, 31-32, 36, 39, 42-47, 50-57, 60, 63-68, 71-76, 79 |
| devices/errors.py              |        1 |        0 |        0 |        0 |    100% |           |
| devices/fluke.py               |      171 |       70 |       16 |        1 |     60% |89, 92, 95, 98, 101, 104, 107, 116, 141-144, 148-150, 153, 164-167, 179, 182-186, 196-200, 203, 206-208, 220, 223-227, 232-234, 238, 241, 244-249, 252-258, 261, 264-268, 271-275, 278 |
| devices/ilx.py                 |      101 |       50 |        6 |        1 |     49% |37, 62, 66, 73, 76-80, 83-87, 90-94, 100-107, 110-113, 116-121, 124, 127-131, 134, 137, 140, 143-147 |
| devices/keithley.py            |      119 |       53 |       10 |        2 |     57% |34-39, 42, 72, 75, 78, 81-84, 94-95, 98-105, 108-114, 119, 121-122, 149, 152, 155, 163-167, 170, 174, 177-184, 187, 190, 193, 222-225 |
| devices/keysight.py            |      138 |       64 |        4 |        0 |     54% |37-38, 52, 55-59, 62-67, 70-75, 78-83, 86-91, 110-113, 116, 126-133, 136, 166, 169, 172-180, 194-196, 204-208, 211, 214, 217, 223, 226 |
| endpoints/\_\_init\_\_.py      |        3 |        0 |        0 |        0 |    100% |           |
| endpoints/filewriter.py        |       66 |        5 |       14 |        3 |     90% |47-\>50, 74-\>exit, 77-78, 87, 111-112 |
| endpoints/mqtt.py              |      113 |       17 |       28 |        3 |     80% |178-\>exit, 182, 196-\>199, 207-209, 211, 216-232, 235, 253-254 |
| errors.py                      |        4 |        0 |        0 |        0 |    100% |           |
| factories/\_\_init\_\_.py      |        3 |        0 |        0 |        0 |    100% |           |
| factories/device\_factory.py   |       16 |        0 |        0 |        0 |    100% |           |
| factories/endpoint\_factory.py |        5 |        0 |        0 |        0 |    100% |           |
| factories/generic\_factory.py  |       17 |        3 |        0 |        0 |     82% | 40, 65-66 |
| logger/\_\_init\_\_.py         |        2 |        0 |        0 |        0 |    100% |           |
| logger/logger.py               |      350 |      125 |       30 |        0 |     67% |228, 283-285, 288, 291, 294-298, 301, 328-331, 354-357, 360-367, 392-395, 428-431, 434-438, 471-477, 480-487, 493-506, 556-557, 560-567, 576-583, 604-606, 621-624, 627-631, 637-640, 647, 650, 653, 656, 659, 662, 677-679, 683-692, 725-731, 735-737, 755, 770-773, 776-778, 789-797, 822-828, 831-833, 851, 856-858 |
| **TOTAL**                      | **1509** |  **494** |  **172** |   **20** | **68%** |           |


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