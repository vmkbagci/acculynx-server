using Newtonsoft.Json;

namespace StackOverflowLibrary.Entities
{
    /// <summary>
    /// A representation of a StackOverflow Answer object.
    /// Extracted from the JSON Question definition in StackOverflow documents.
    /// </summary>
    public class Answer
    {
        [JsonProperty("owner")]
        public ShallowUser Owner { get; set; }

        [JsonProperty("is_accepted")]
        public bool IsAccepted { get; set; }

        [JsonProperty("score")]
        public int Score { get; set; }

        [JsonProperty("answer_id")]
        public int AnswerId { get; set; }

        [JsonProperty("link")]
        public string Link { get; set; }

        [JsonProperty("up_vote_count")]
        public int? UpVoteCount { get; set; }

        [JsonProperty("down_vote_count")]
        public int? DownVoteCount { get; set; }

        [JsonProperty("title")]
        public string Title { get; set; }

        [JsonProperty("body")]
        public string Body { get; set; }
    }
}
