import logging
import unittest
from unittest import mock

import requests
import responses

import documents


logging.basicConfig()

responses.get("https://ipv4.webshare.io/", "0.0.0.0")

ORDER_ID = "1"
APPLICATION_ID = "a"


class DocumentsUploaderTestCase(unittest.TestCase):
    def setUp(self):
        self.doc_uploader = documents.DocumentsUploader()
        self.doc_uploader.parallel_document_upload = False
        self.doc_uploader.order_id = ORDER_ID
        self.doc_uploader.application_id = APPLICATION_ID
        self.doc_uploader.mylogger = logging.getLogger()
        self.doc_uploader.token = ""
        self.doc_uploader.user_agent = ""
        self.doc_uploader.session = requests.Session()
        self.doc_uploader.proxy_apply = False
        self.doc_uploader.get_token_requests = mock.MagicMock
        self.doc_uploader.get_token_requests.return_value = ""
        self.doc_uploader.run_auth = mock.MagicMock
        self.doc_uploader.run_auth.return_value = ""

        responses.get(
            f"https://v3bl.goszakup.gov.kz/ru/application/docs/{ORDER_ID}/{APPLICATION_ID}",
            """
            <html>
            <body>
            <table class="table table-bordered table-striped table-hover">
                <tr><td></td></tr>
                <tr>
                    <td>
                        <span class="glyphicon glyphicon-remove-circle">
                        <a href="https://v3bl.goszakup.gov.kz/ru/application/docs/doc_1">Приложение 1 </a>
                        </span>
                    </td>
                </tr>
                <tr>
                    <td>
                        <span class="glyphicon glyphicon-remove-circle">
                        <a href="https://v3bl.goszakup.gov.kz/ru/application/docs/doc_2">Приложение 2 </a>
                        </span>
                    </td>
                </tr>
            </table>
            </body>
            </html>
            """
        )

    @responses.activate
    def test_upload_serial(self):
        self.doc_uploader.parallel_document_upload = False
        with mock.patch("documents.DocumentsUploader.upload_document") as upload:
            upload.return_value = False
            self.doc_uploader.upload_documents(wait_affiliates=False)
            self.assertIn(mock.call(0, mock.ANY), upload.call_args_list)
            self.assertIn(mock.call(1, mock.ANY), upload.call_args_list)

    @responses.activate
    def test_upload_parallel(self):
        self.doc_uploader.parallel_document_upload = True
        with mock.patch("documents.DocumentsUploader.upload_document") as upload:
            upload.return_value = False
            self.doc_uploader.upload_documents(wait_affiliates=False)
            self.assertIn(mock.call(0, mock.ANY), upload.call_args_list)
            self.assertIn(mock.call(1, mock.ANY), upload.call_args_list)
    
    @responses.activate
    def test_upload_parallel2(self):
        self.doc_uploader.parallel_document_upload = True
        with mock.patch("documents.DocumentsUploader.form1") as form1:
            form1.return_value = None
            with mock.patch("documents.DocumentsUploader.form2") as form2:
                form2.return_value = None
                self.doc_uploader.upload_documents(wait_affiliates=False)
                form1.assert_called_once()
                form2.assert_called_once()








if __name__ == "__main__":
    unittest.main()
