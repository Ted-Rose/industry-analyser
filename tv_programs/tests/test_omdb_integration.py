import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from tv_programs.scraper import TVProgramScraper


class OMDBIntegrationTest(TestCase):

    def setUp(self):
        self.scraper = TVProgramScraper()

    @patch('tv_programs.scraper.TVProgramScraper.make_request')
    def test_get_omdb_data_success(self, mock_make_request):
        """Test successful retrieval of OMDb data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.data = json.dumps({
            "Response": "True",
            "Title": "Test Movie",
            "Year": "2023",
            "imdbID": "tt1234567"
        }).encode()
        mock_make_request.return_value = mock_response

        result = self.scraper.get_omdb_data("Test Movie", year="2023")

        self.assertIsNotNone(result)
        self.assertEqual(result['Title'], "Test Movie")
        mock_make_request.assert_called_once()

    @patch('tv_programs.scraper.TVProgramScraper.make_request')
    def test_get_omdb_data_not_found(self, mock_make_request):
        """Test handling of a 'Movie not found' response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.data = json.dumps({"Response": "False", "Error": "Movie not found!"}).encode()
        mock_make_request.return_value = mock_response

        result = self.scraper.get_omdb_data("Unknown Movie")

        self.assertIsNone(result)

    @patch('tv_programs.scraper.TVProgramScraper._omdb_request')
    def test_fallback_search(self, mock_omdb_request):
        """Test the fallback search mechanism."""
        # First call for title fails
        mock_omdb_request.side_effect = [
            None,  # Direct title match fails
            {  # Search call succeeds
                "Search": [{"Title": "Found Movie", "imdbID": "tt7654321"}],
                "Response": "True"
            },
            {  # Get by ID succeeds
                "Title": "Found Movie",
                "imdbID": "tt7654321",
                "Response": "True"
            }
        ]

        result = self.scraper.get_omdb_data("NonExistent Movie")

        self.assertIsNotNone(result)
        self.assertEqual(result['Title'], "Found Movie")
        self.assertEqual(mock_omdb_request.call_count, 3)

    def test_rate_limiting(self):
        """Test that the scraper respects the rate limit."""
        self.scraper.omdb_request_count = self.scraper.omdb_request_limit
        result = self.scraper.get_omdb_data("Test Movie")
        self.assertIsNone(result)

    def test_field_mapping(self):
        """Test the mapping of OMDb fields to the program dictionary."""
        omdb_data = {
            "Title": "Test Title",
            "Plot": "Test Plot",
            "Poster": "http://example.com/poster.jpg",
            "imdbID": "tt123",
            "Rated": "PG-13",
            "imdbRating": "8.5",
            "Released": "01 Jan 2023",
            "Type": "movie"
        }
        program_data = MagicMock()
        program_data.find.return_value = None  # No tet image

        processed = self.scraper.process_item(program_data, omdb_data, "LV Title", "LV Desc")

        self.assertEqual(processed['title_eng'], "Test Title")
        self.assertEqual(processed['description_eng'], "Test Plot")
        self.assertEqual(processed['image_url'], "http://example.com/poster.jpg")
        self.assertEqual(processed['url'], "https://www.imdb.com/title/tt123/")
        self.assertEqual(processed['pg_rating'], "PG-13")
        self.assertEqual(processed['imdb_rating'], "8.5")
