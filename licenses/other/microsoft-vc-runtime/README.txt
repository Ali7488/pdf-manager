Microsoft Visual C++ runtime files in PDF Manager for Windows

Files: vcruntime140.dll, vcruntime140_1.dll and msvcp140*.dll in the _internal folder.
Copyright (c) Microsoft Corporation. All rights reserved.

These are Microsoft's Visual C++ runtime libraries. The Python runtime and PyMuPDF
were built with Microsoft Visual C++ and need them. They are not open source and are
not covered by PDF Manager's licences. Microsoft lets them be redistributed with a
program, unmodified, under the "Distributable Code" terms of the Visual Studio licence;
the list of such files is at
https://learn.microsoft.com/visualstudio/releases/2022/redistribution
("Visual C++ Runtime Files"). The python.org Windows build's own conditions for them
are in python-runtime-windows-*/LICENSE.txt, under "Additional Conditions for this
Windows binary build".

The same files are installed system-wide by Microsoft's Visual C++ Redistributable:
https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist
