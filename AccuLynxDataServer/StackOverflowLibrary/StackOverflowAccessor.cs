using Newtonsoft.Json.Linq;
using StackOverflowLibrary.Entities;
using StackOverflowLibrary.ExtensionsAndHelpers;
using System.Formats.Asn1;
using System.Net;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;

namespace StackOverflowLibrary
{
    public class StackOverflowAccessor : IStackOverflowAccessor
    {
        private HttpClient httpClient;
        private readonly string StackOverflowApiBaseUrl = "https://api.stackexchange.com/2.3/";

        public StackOverflowAccessor()
        {
            this.SetHttpClient();
        }

        public StackOverflowAccessor(string stackOverflowApiBaseUrl)
        {
            StackOverflowApiBaseUrl = stackOverflowApiBaseUrl;
            this.SetHttpClient();
        }

        private void SetHttpClient()
        {
            var handler = new HttpClientHandler
            {
                AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate
            };

            httpClient = new HttpClient(handler)
            {
                BaseAddress = new Uri(StackOverflowApiBaseUrl)
            };

            httpClient.DefaultRequestHeaders.Accept.Clear();
            httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        }

        /// <inheritdoc/>
        public async Task<List<int>> GetQuestionIdsWithAnswers(DateTime createdAtOrAfterDate)
        {
            var fromDateUTS = createdAtOrAfterDate.ToUnixTimestamp();
            var toDateUTS = createdAtOrAfterDate.AddDays(1).ToUnixTimestamp();

            var query = $"questions?fromdate={fromDateUTS}&toDate={toDateUTS}&site=stackoverflow";

            var response = await httpClient.GetAsync(query.ToString());

            response.EnsureSuccessStatusCode();
            var responseBody = await response.Content.ReadAsStringAsync();
            var result = JObject.Parse(responseBody);

            var items = result["items"];
            var questionIds = new List<int>();

            foreach (var item in items)
            {
                int answerCount = item.Value<int>("answer_count");
                bool isAnswered = item.Value<bool>("is_answered");
                if (answerCount > 1 && isAnswered)
                {
                    questionIds.Add(item.Value<int>("question_id"));
                }
            }

            return questionIds;
        }

        /// <inheritdoc/>
        public async Task<List<int>> GetQuestionIdsWithAnswers(DateTime createdAtOrAfterDate, string[] mustHaveTags)
        {
            throw new NotImplementedException();
        }

        public async Task<Question> GetQuestionById(int id)
        {
            var questionQuery = $"questions/{id}?order=desc&sort=activity&site=stackoverflow&filter=!nOedRLbBQj";

            var questionResponse = await httpClient.GetAsync(questionQuery.ToString());
            questionResponse.EnsureSuccessStatusCode();
            var questionResponseBody = await questionResponse.Content.ReadAsStringAsync();
            
            var result = JObject.Parse(questionResponseBody);

            var items = result["items"];

            if (items == null) return null;

            var question = (items[0] as JObject).ToObject<Question>();
            
            var answersQuery = $"questions/{id}/answers?order=desc&sort=activity&site=stackoverflow&filter=!6Wfm_gUdxFeTe";

            var answersResponse = await httpClient.GetAsync(answersQuery.ToString());
            answersResponse.EnsureSuccessStatusCode();
            var answersResponseBody = await answersResponse.Content.ReadAsStringAsync();

            var answersResult = JObject.Parse(answersResponseBody);

            var answerItems = answersResult["items"];

            if (answerItems == null) return null;

            var answers = answerItems.ToObject<List<Answer>>();

            answers.ForEach(ans => question.Answers.Add(ans));

            return question;
        }
    }
}
