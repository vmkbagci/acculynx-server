using Newtonsoft.Json;

namespace StackOverflowLibrary.Entities
{
    /// <summary>
    /// A representation of a StackOverflow User object.
    /// Extracted from the JSON Question definition in StackOverflow documents.
    /// </summary>
    public class ShallowUser
    {
        [JsonProperty("user_id")]
        public int UserId { get; set; }

        [JsonProperty("display_name")]
        public string DisplayName { get; set; }

        [JsonProperty("reputation")]
        public int Reputation { get; set; }
    }
}
