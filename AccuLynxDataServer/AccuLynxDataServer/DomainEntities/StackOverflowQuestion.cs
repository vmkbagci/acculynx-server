using StackOverflowLibrary.Entities;

namespace AccuLynxDataServer.DomainEntities
{
    public class StackOverflowQuestion
    {
        public string OwnerDisplayName { get; set; }
        public int OwnerReputation { get; set; }
        public int Score { get; set; }
        public int QuestionId { get; set; }
        public string Title { get; set; }
        public int? AcceptedAnswerId { get; set; }
    }
}
