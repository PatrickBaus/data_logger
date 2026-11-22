# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| \_version.py                   |        1 |        0 |        0 |        0 |    100% |           |
| data\_logger.py                |      146 |       12 |       22 |        4 |     89% |90, 191, 194-196, 275, 281-290, 294, 298, 304 |
| devices/\_\_init\_\_.py        |        8 |        0 |        0 |        0 |    100% |           |
| devices/async\_ethernet.py     |       59 |        6 |       10 |        3 |     87% |37, 41, 46, 83, 101-\>exit, 110-\>exit, 117-118 |
| devices/async\_serial.py       |       87 |       27 |       28 |        3 |     70% |69, 73, 133-142, 155-157, 169, 179-180, 184-195 |
| devices/coherent.py            |       48 |       31 |        2 |        0 |     34% |28, 31-32, 35-36, 41, 45, 48, 51-56, 59-66, 69, 72-77, 80-81 |
| devices/e\_plus\_e.py          |       45 |       31 |        2 |        0 |     30% |26, 29-30, 34, 37, 40-45, 48-55, 58, 61-66, 69-74, 77 |
| devices/errors.py              |        1 |        0 |        0 |        0 |    100% |           |
| devices/fluke.py               |      169 |       70 |       16 |        1 |     59% |85, 88, 91, 94, 97, 100, 103, 112, 137-140, 144-146, 149, 160-163, 175, 178-182, 192-196, 199, 202-204, 216, 219-223, 228-230, 234, 237, 240-245, 248-254, 257, 260-264, 267-271, 274 |
| devices/ilx.py                 |      101 |       51 |        6 |        1 |     48% |35, 60, 64, 71, 74-78, 81-85, 88-92, 98-105, 108-111, 114-120, 123, 126-130, 133, 136, 139, 142-146 |
| devices/keithley.py            |      116 |       76 |       10 |        0 |     32% |26, 29-34, 37, 40, 44-47, 50-51, 55, 58, 61, 64-67, 77-78, 81-88, 91-97, 100-105, 109-112, 115-117, 120, 123, 126, 131, 134-138, 141, 145, 148-155, 158, 161, 164, 167, 171-174, 177-178, 181-184 |
| devices/keysight.py            |      136 |       65 |        4 |        1 |     51% |34-35, 49, 52-56, 59-64, 67-72, 75-80, 83-88, 107-110, 113, 123-130, 133, 143, 151, 154, 157-165, 179-181, 189-193, 196, 199, 202, 208, 211 |
| endpoints/\_\_init\_\_.py      |        2 |        0 |        0 |        0 |    100% |           |
| endpoints/filewriter.py        |       65 |        5 |       14 |        3 |     90% |46-\>49, 73-\>exit, 76-77, 86, 110-111 |
| endpoints/mqtt.py              |      113 |       17 |       28 |        3 |     80% |181-\>exit, 185, 199-\>202, 210-212, 214, 219-235, 238, 256-257 |
| errors.py                      |        4 |        0 |        0 |        0 |    100% |           |
| factories/\_\_init\_\_.py      |        2 |        0 |        0 |        0 |    100% |           |
| factories/device\_factory.py   |       14 |        0 |        0 |        0 |    100% |           |
| factories/endpoint\_factory.py |        5 |        0 |        0 |        0 |    100% |           |
| factories/generic\_factory.py  |       15 |        3 |        0 |        0 |     80% | 30, 55-56 |
| logger/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| logger/logger.py               |      333 |      121 |       32 |        0 |     66% |255-257, 260, 263, 266-270, 273, 300-303, 326-329, 332-339, 364-367, 400-403, 406-410, 443-449, 452-459, 465-478, 528-529, 532-539, 548-555, 576-578, 593-596, 599-603, 609-612, 627-632, 636-645, 656, 681-687, 691-693, 711, 726-729, 732-734, 745-753, 778-784, 787-789, 807, 812-814 |
| **TOTAL**                      | **1471** |  **515** |  **174** |   **19** | **65%** |           |


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