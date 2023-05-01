using Newtonsoft.Json;

namespace StackOverflowLibrary.Entities
{
    /// <summary>
    /// A representation of a StackOverflow Question object.
    /// Extracted from the JSON Question definition in StackOverflow documents.
    /// </summary>
    public class Question
    {
        [JsonProperty("tags")]
        public List<string> Tags { get; set; } = new List<string>();

        [JsonProperty("owner")]
        public ShallowUser Owner { get; set; }

        [JsonProperty("question_id")]
        public int QuestionId { get; set; }

        [JsonProperty("accepted_answer_id")]
        public int? AcceptedAnswerId { get; set; }

        [JsonProperty("link")]
        public string Link { get; set; }

        [JsonProperty("title")]
        public string Title { get; set; }

        [JsonProperty("body")]
        public string Body { get; set; }

        [JsonProperty("view_count")]
        public int ViewCount { get; set; }

        [JsonProperty("answer_count")]
        public int AnswerCount { get; set; }

        [JsonProperty("score")]
        public int Score { get; set; }

        public ICollection<Answer> Answers { get; set; } = new List<Answer>();
    }

}
