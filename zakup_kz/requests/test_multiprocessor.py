import unittest
from unittest import mock

import responses

import multiprocessor


class MultiprocessorTestCase(unittest.TestCase):
    def setUp(self):
        self.processor = multiprocessor.MultiProcessor(
            config_path="config.json",
            delay502=10,
            delay502_increment=1
        )
        responses.get("https://ipv4.webshare.io/", "0.0.0.0")

    @responses.activate 
    def test_delay(self):
        # Make sure that we call multi_monitor with the proper delay parameters.
        self.assertEqual(self.processor.delay502, 10)
        self.assertEqual(self.processor.delay502_increment, 1)

        with mock.patch("auth.AuthClass.run_auth") as run_auth:
            run_auth.return_value = False
            with mock.patch("monitor.Monitor.multi_monitor") as multi_monitor:
                multi_monitor.return_value = None
                self.processor.run()
                multi_monitor.assert_called_once_with(
                    delay_502=self.processor.delay502,
                    delay_502_increment=self.processor.delay502_increment
                )

    def test_stats(self):
        self.processor.order = ""
        self.processor.auth_end_time, self.processor.auth_start_time = 10, 0
        self.processor.create_end_time, self.processor.create_start_time = 20, 10
        self.processor.documents_end_time, self.processor.documents_start_time = 30, 20
        self.processor.affiliate_end_time, self.processor.affiliate_start_time = 40, 30
        self.processor.prices_end_time, self.processor.prices_start_time = 50, 40
        stats = self.processor.get_stats()
        self.assertIn("TOTAL AUTH TIME 10.0", stats)
        self.assertIn("APPLICATION CREATION 10.0", stats)
        self.assertIn("DOCUMENTS UPLOAD TIME 10.0", stats)
        self.assertIn("AFFILIATE WAIT 10.0", stats)
        self.assertIn("PRICES UPLOAD 10.0", stats)

    @mock.patch("documents.DocumentsUploader.upload_documents")
    @mock.patch("create_application.ApplicationCreator.create_application")
    @mock.patch("monitor.Monitor.tax_debt_upload")
    @mock.patch("monitor.Monitor.multi_monitor")
    @mock.patch("auth.AuthClass.run_auth")
    @responses.activate 
    def test_wait_affiliates_true(self, run_auth, multi_monitor, tax_debt_upload, create_application, upload_documents):
        run_auth.return_value = False
        multi_monitor.return_value = {"order_id": 1}
        tax_debt_upload.return_value = None
        create_application.return_value = None
        upload_documents.side_effect = KeyError("")

        processor = multiprocessor.MultiProcessor(
            config_path="config.json",
            wait_affiliates=True
        )
        self.assertRaises(KeyError, processor.run)
        upload_documents.assert_called_once_with(wait_affiliates=True)

    @mock.patch("documents.DocumentsUploader.upload_documents")
    @mock.patch("create_application.ApplicationCreator.create_application")
    @mock.patch("monitor.Monitor.tax_debt_upload")
    @mock.patch("monitor.Monitor.multi_monitor")
    @mock.patch("auth.AuthClass.run_auth")
    @responses.activate 
    def test_wait_affiliates_false(self, run_auth, multi_monitor, tax_debt_upload, create_application, upload_documents):
        run_auth.return_value = False
        multi_monitor.return_value = {"order_id": 1}
        tax_debt_upload.return_value = None
        create_application.return_value = None
        upload_documents.side_effect = KeyError("")
        processor = multiprocessor.MultiProcessor(
            config_path="config.json",
            wait_affiliates=False
        )
        self.assertRaises(KeyError, processor.run)
        upload_documents.assert_called_once_with(wait_affiliates=False)


class MultiProcessingMainTestCase(unittest.TestCase):
    def test_exception_delay(self):
        exception_delay = 20
        args = multiprocessor.parser.parse_args([
            "--config=config.json",
            f"--exception-delay={exception_delay}",
        ])
        with mock.patch("multiprocessor.MultiProcessor.run") as run:
            run.side_effect = [KeyError, None]
            with mock.patch("time.sleep") as sleep:
                multiprocessor.main(args)
                sleep.assert_called_once_with(exception_delay)

    def test_parallel_document_upload_on(self):
        args = multiprocessor.parser.parse_args([
            "--config=config.json",
            "--parallel-document-upload",
        ])
        with mock.patch("multiprocessor.MultiProcessor.run") as run:
            run.return_value = None
            with mock.patch("time.sleep") as sleep:
                proc = multiprocessor.main(args)
                self.assertTrue(proc.parallel_document_upload)

    def test_parallel_document_upload_off(self):
        args = multiprocessor.parser.parse_args([
            "--config=config.json",
        ])
        with mock.patch("multiprocessor.MultiProcessor.run") as run:
            run.return_value = None
            with mock.patch("time.sleep") as sleep:
                proc = multiprocessor.main(args)
                self.assertFalse(proc.parallel_document_upload)

    def test_wait_affiliates(self):
        with mock.patch("multiprocessor.MultiProcessor.run") as run:
            run.return_value = None
            with mock.patch("time.sleep") as sleep:
                args = ["--config=config.json"]
                proc = multiprocessor.main(
                    multiprocessor.parser.parse_args(args))
                self.assertTrue(proc.wait_affiliates)

                args = ["--config=config.json", "--wait-affiliates=1"]
                proc = multiprocessor.main(
                    multiprocessor.parser.parse_args(args))
                self.assertTrue(proc.wait_affiliates)
                
                args = ["--config=config.json", "--wait-affiliates=0"]
                proc = multiprocessor.main(
                    multiprocessor.parser.parse_args(args))
                self.assertFalse(proc.wait_affiliates)


if __name__ == "__main__":
    unittest.main()
