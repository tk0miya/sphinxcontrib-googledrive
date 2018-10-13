sphinxcontrib-googledrive
=========================

This Sphinx extension allows you to embed images on `Google Drive`_ into your document::

  .. image:: https://docs.google.com/drawings/d/1Q687-tVfqOMh86-16yl64misTee2bO5KPNuV5-LZ5FE/edit

.. _Google Drive: https://www.google.com/drive/


Setting
=======

Install
-------

::

   $ pip install sphinxcontrib-googledrive


Prepare your Google Apps
------------------------

This extension expects you to create Google Apps and its Service Account.
Please read the document of `Google Client Libraries: Using OAuth 2.0 for
Server to Server Applications`_ and create your service account.  And
please generate a private key for the account.

.. _Google Client Libraries: Using OAuth 2.0 for Server to Server Applications`: https://developers.google.com/api-client-library/python/auth/service-accounts

Configure Sphinx
----------------

Add ``sphinxcontrib.googledrive`` to ``extensions`` at `conf.py`::

   extensions += ['sphinxcontrib.googledrive']

And let the private key for your service account to Sphinx through one of
the following methods:

1. Set content of the private key via environment variable
   `GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY`::

     $ export GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY='{"type": "service_account", ...}'

2. Set a path to the private key file via `googledrive_service_account`
   in `conf.py`::

     googledrive_service_account = '/path/to/private.key'


Usage
=====

Please give an URL of caoo diagrams to image_ or figure_ directives
as an argument::

  .. image:: https://docs.google.com/drawings/d/1Q687-tVfqOMh86-16yl64misTee2bO5KPNuV5-LZ5FE/edit

  .. figure:: https://docs.google.com/drawings/d/1Q687-tVfqOMh86-16yl64misTee2bO5KPNuV5-LZ5FE/edit

     caption of figure

.. _image: http://docutils.sourceforge.net/docs/ref/rst/directives.html#image
.. _figure: http://docutils.sourceforge.net/docs/ref/rst/directives.html#figure


Repository
==========

https://github.com/tk0miya/sphinxcontrib-googledrive
